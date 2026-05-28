"""Tests for the i18n loader infrastructure.

Per spec §4.4 validation contract. Uses tmp_path fixtures (NOT the real
modules/i18n/ directory) to avoid coupling these tests to Task 4 YAML content.
"""
import logging
import pytest
import yaml
from pathlib import Path

from modules.i18n.loader import I18nLoader, ValidationReport
from modules.i18n.registry import StringRegistry, StringEntry, MissingKeyError, RUNTIME_FALLBACK_LANG


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def tmp_i18n_dir(tmp_path: Path) -> Path:
    """Build a minimal valid schema + en + id YAMLs under tmp_path."""
    (tmp_path / "schema.yaml").write_text(
        yaml.safe_dump({
            "greetings.hello": {
                "surface": "test",
                "placeholders": ["name"],
                "max_words": 5,
                "tone": "professional_courteous",
                "required_for": ["en", "id"],
            }
        }),
        encoding="utf-8",
    )
    strings_dir = tmp_path / "strings"
    strings_dir.mkdir()
    (strings_dir / "en.yaml").write_text(
        yaml.safe_dump({
            "greetings.hello": {"text": "Hello, {name}!", "status": "verified"},
        }),
        encoding="utf-8",
    )
    (strings_dir / "id.yaml").write_text(
        yaml.safe_dump({
            "greetings.hello": {"text": "Halo, {name}!", "status": "verified"},
        }),
        encoding="utf-8",
    )
    return tmp_path


# ============================================================================
# Core lookup + substitution
# ============================================================================


def test_verified_translation_renders_with_substitution(tmp_i18n_dir):
    # LC-1 — verified entry renders with placeholder substitution
    registry = I18nLoader(base_dir=tmp_i18n_dir).load()
    assert registry.t("greetings.hello", "en", name="World") == "Hello, World!"
    assert registry.t("greetings.hello", "id", name="Dunia") == "Halo, Dunia!"


def test_unknown_lang_falls_back_to_english(tmp_i18n_dir):
    # Runtime fallback: requesting a lang that has no entry should render English
    registry = I18nLoader(base_dir=tmp_i18n_dir).load()
    out = registry.t("greetings.hello", "ja", name="World")
    assert out == "Hello, World!"


def test_runtime_render_with_unknown_placeholder_raises():
    # Placeholder substitution failure surfaces as KeyError at render time
    reg = StringRegistry()
    reg.entries[("k", "en")] = StringEntry(text="Hi {name}", status="verified")
    with pytest.raises(KeyError):
        reg.t("k", "en")  # 'name' kwarg missing


def test_registry_has_lookup():
    reg = StringRegistry()
    reg.entries[("k", "en")] = StringEntry(text="x", status="verified")
    assert reg.has("k", "en")
    assert not reg.has("k", "id")
    assert not reg.has("nonexistent", "en")


# ============================================================================
# Validation contract — CRITICAL (refuse to start)
# ============================================================================


def test_missing_required_key_raises_critical_on_load(tmp_path):
    # LC-5 — CRITICAL: required key absent from required-lang YAML
    (tmp_path / "schema.yaml").write_text(
        yaml.safe_dump({"k": {"placeholders": [], "required_for": ["en", "id"]}}),
        encoding="utf-8",
    )
    (tmp_path / "strings").mkdir()
    (tmp_path / "strings" / "en.yaml").write_text(
        yaml.safe_dump({"k": {"text": "ok", "status": "verified"}}),
        encoding="utf-8",
    )
    (tmp_path / "strings" / "id.yaml").write_text(yaml.safe_dump({}), encoding="utf-8")

    with pytest.raises(MissingKeyError, match="absent from id.yaml"):
        I18nLoader(base_dir=tmp_path).load()


def test_placeholder_mismatch_raises_critical_on_load(tmp_path):
    # LC-5 — CRITICAL: placeholder mismatch between schema and YAML text
    (tmp_path / "schema.yaml").write_text(
        yaml.safe_dump({"k": {"placeholders": ["name"], "required_for": ["en"]}}),
        encoding="utf-8",
    )
    (tmp_path / "strings").mkdir()
    (tmp_path / "strings" / "en.yaml").write_text(
        yaml.safe_dump({"k": {"text": "Hello {wrong_placeholder}", "status": "verified"}}),
        encoding="utf-8",
    )

    with pytest.raises(MissingKeyError, match="Placeholder mismatch"):
        I18nLoader(base_dir=tmp_path).load()


def test_extra_placeholder_in_yaml_raises_critical(tmp_path):
    (tmp_path / "schema.yaml").write_text(
        yaml.safe_dump({"k": {"placeholders": [], "required_for": ["en"]}}),
        encoding="utf-8",
    )
    (tmp_path / "strings").mkdir()
    (tmp_path / "strings" / "en.yaml").write_text(
        yaml.safe_dump({"k": {"text": "Hello {extra}", "status": "verified"}}),
        encoding="utf-8",
    )

    with pytest.raises(MissingKeyError, match="Placeholder mismatch"):
        I18nLoader(base_dir=tmp_path).load()


# ============================================================================
# Validation contract — WARN (do not block)
# ============================================================================


def test_status_missing_at_startup_logs_warn_not_critical(tmp_i18n_dir, caplog):
    # NEW row in §4.4 (per user Issue #1 review):
    # required key present with status=missing is WARN, NOT CRITICAL —
    # loader continues; deploy-time visibility for ops.
    (tmp_i18n_dir / "strings" / "id.yaml").write_text(
        yaml.safe_dump({"greetings.hello": {"text": "", "status": "missing"}}),
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING):
        registry = I18nLoader(base_dir=tmp_i18n_dir).load()

    # Loader did NOT raise. Registry is populated. WARN was logged.
    assert registry is not None
    warn_records = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "i18n_validation_warn" in r.message
    ]
    assert len(warn_records) >= 1


def test_status_missing_at_startup_validation_report_classifies_warn(tmp_i18n_dir):
    (tmp_i18n_dir / "strings" / "id.yaml").write_text(
        yaml.safe_dump({"greetings.hello": {"text": "", "status": "missing"}}),
        encoding="utf-8",
    )

    report = I18nLoader(base_dir=tmp_i18n_dir).validate()
    warn_issues = report.warn_issues()
    assert any(i.key == "greetings.hello" and i.lang == "id" for i in warn_issues)
    assert not report.has_critical


# ============================================================================
# Runtime fallback (LC-4)
# ============================================================================


def test_missing_status_renders_english_fallback(tmp_i18n_dir, caplog):
    # LC-4 — runtime: requesting an entry whose status is "missing" falls back to en
    (tmp_i18n_dir / "strings" / "id.yaml").write_text(
        yaml.safe_dump({"greetings.hello": {"text": "", "status": "missing"}}),
        encoding="utf-8",
    )

    registry = I18nLoader(base_dir=tmp_i18n_dir).load()
    with caplog.at_level(logging.WARNING):
        out = registry.t("greetings.hello", "id", name="World")

    assert out == "Hello, World!"  # English fallback rendered
    assert any("i18n_runtime_fallback" in r.message for r in caplog.records)


def test_deprecated_status_renders_english_fallback(tmp_i18n_dir):
    (tmp_i18n_dir / "strings" / "id.yaml").write_text(
        yaml.safe_dump({"greetings.hello": {"text": "outdated", "status": "deprecated"}}),
        encoding="utf-8",
    )

    registry = I18nLoader(base_dir=tmp_i18n_dir).load()
    out = registry.t("greetings.hello", "id", name="World")
    assert out == "Hello, World!"


def test_missing_in_both_langs_raises_missing_key_error():
    reg = StringRegistry()
    with pytest.raises(MissingKeyError):
        reg.t("never.defined", "en")


# ============================================================================
# Validation contract — INFO (baseline_hash drift → auto-flip stale)
# ============================================================================


def test_baseline_hash_mismatch_flips_to_stale_re_review(tmp_path):
    """INFO severity, NOT blocking — entry stays usable with status updated."""
    (tmp_path / "schema.yaml").write_text(
        yaml.safe_dump({"k": {"placeholders": [], "required_for": ["en", "id"]}}),
        encoding="utf-8",
    )
    (tmp_path / "strings").mkdir()
    (tmp_path / "strings" / "en.yaml").write_text(
        yaml.safe_dump({"k": {"text": "Hello current baseline", "status": "verified"}}),
        encoding="utf-8",
    )
    (tmp_path / "strings" / "id.yaml").write_text(
        yaml.safe_dump({
            "k": {
                "text": "Halo",
                "status": "verified",
                "baseline_hash": "not_the_current_hash_at_all",
            }
        }),
        encoding="utf-8",
    )

    registry = I18nLoader(base_dir=tmp_path).load()
    entry = registry.entries[("k", "id")]
    assert entry.status == "stale_re_review"


def test_matching_baseline_hash_keeps_verified(tmp_path):
    import hashlib
    en_text = "Hello"
    en_hash = hashlib.sha256(en_text.encode("utf-8")).hexdigest()

    (tmp_path / "schema.yaml").write_text(
        yaml.safe_dump({"k": {"placeholders": [], "required_for": ["en", "id"]}}),
        encoding="utf-8",
    )
    (tmp_path / "strings").mkdir()
    (tmp_path / "strings" / "en.yaml").write_text(
        yaml.safe_dump({"k": {"text": en_text, "status": "verified"}}),
        encoding="utf-8",
    )
    (tmp_path / "strings" / "id.yaml").write_text(
        yaml.safe_dump({
            "k": {"text": "Halo", "status": "verified", "baseline_hash": en_hash}
        }),
        encoding="utf-8",
    )

    registry = I18nLoader(base_dir=tmp_path).load()
    entry = registry.entries[("k", "id")]
    assert entry.status == "verified"


# ============================================================================
# Draft / needs_revision / stale render normally (with INFO logging)
# ============================================================================


def test_draft_status_renders_text(tmp_i18n_dir, caplog):
    (tmp_i18n_dir / "strings" / "id.yaml").write_text(
        yaml.safe_dump({"greetings.hello": {"text": "Halo, {name}!", "status": "draft"}}),
        encoding="utf-8",
    )

    registry = I18nLoader(base_dir=tmp_i18n_dir).load()
    with caplog.at_level(logging.INFO):
        out = registry.t("greetings.hello", "id", name="Tester")

    assert out == "Halo, Tester!"
    assert any("i18n_draft_translation_used" in r.message for r in caplog.records)


def test_needs_revision_status_renders_text(tmp_i18n_dir, caplog):
    (tmp_i18n_dir / "strings" / "id.yaml").write_text(
        yaml.safe_dump({"greetings.hello": {"text": "Halo, {name}!", "status": "needs_revision"}}),
        encoding="utf-8",
    )

    registry = I18nLoader(base_dir=tmp_i18n_dir).load()
    with caplog.at_level(logging.INFO):
        out = registry.t("greetings.hello", "id", name="Tester")

    assert out == "Halo, Tester!"
    assert any("i18n_needs_revision_translation_used" in r.message for r in caplog.records)


# ============================================================================
# List-typed entries (greeting.palette, abandonment.trigger_phrases)
# ============================================================================


def test_list_typed_entry_returned_as_list(tmp_path):
    (tmp_path / "schema.yaml").write_text(
        yaml.safe_dump({
            "palette.entries": {
                "type": "list",
                "placeholders": [],
                "required_for": ["en"],
            }
        }),
        encoding="utf-8",
    )
    (tmp_path / "strings").mkdir()
    (tmp_path / "strings" / "en.yaml").write_text(
        yaml.safe_dump({
            "palette.entries": {
                "text": ["Hello!", "Hi!", "Hey!"],
                "status": "verified",
            }
        }),
        encoding="utf-8",
    )

    registry = I18nLoader(base_dir=tmp_path).load()
    out = registry.t("palette.entries", "en")
    assert isinstance(out, list)
    assert out == ["Hello!", "Hi!", "Hey!"]


# ============================================================================
# Empty / nonexistent directory edge cases
# ============================================================================


def test_empty_base_dir_loads_empty_registry(tmp_path):
    registry = I18nLoader(base_dir=tmp_path).load()
    assert registry.entries == {}
    assert registry.schema == {}


def test_validate_returns_report_object(tmp_i18n_dir):
    report = I18nLoader(base_dir=tmp_i18n_dir).validate()
    assert isinstance(report, ValidationReport)
    assert not report.has_critical
