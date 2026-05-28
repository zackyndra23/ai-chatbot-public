"""Tests for Tasks 14-19 — palette migration batch.

Verifies lift-and-shift of legacy palette dicts to centralized i18n loader.
Strict-additive: legacy palette dicts stay during 14-18, deleted only in Task 19.
"""
import pytest

from modules.i18n import _get_registry, _reset_registry_for_tests


@pytest.fixture(autouse=True)
def _reset():
    _reset_registry_for_tests()
    yield
    _reset_registry_for_tests()


# ============================================================================
# Task 14 — _GREETING_PALETTE migration (Step 3)
# ============================================================================


def test_task14_schema_has_greeting_palette_key():
    """Schema entry exists with list-typed declaration + en/id required_for."""
    registry = _get_registry()
    assert "greeting.palette" in registry.schema
    meta = registry.schema["greeting.palette"]
    assert meta.get("type") == "list"
    assert "en" in meta.get("required_for", [])
    assert "id" in meta.get("required_for", [])


def test_task14_en_id_greeting_palette_loaded_verified():
    """en + id greeting palettes loaded at status=verified per lift-and-shift."""
    registry = _get_registry()
    en_entry = registry.entries.get(("greeting.palette", "en"))
    id_entry = registry.entries.get(("greeting.palette", "id"))
    assert en_entry is not None
    assert id_entry is not None
    assert en_entry.status == "verified"
    assert id_entry.status == "verified"
    assert isinstance(en_entry.text, list)
    assert isinstance(id_entry.text, list)
    assert "Hi there" in en_entry.text
    assert "Halo" in id_entry.text


def test_task14_all_14_legacy_langs_lifted_into_i18n():
    """Lift-and-shift policy — all 14 legacy palette langs present in i18n.

    Phase 2a en + id at verified; other 12 langs at draft.
    """
    registry = _get_registry()
    expected_langs = {"id", "ms", "en", "fr", "de", "it", "pt", "es",
                      "vi", "th", "da", "zh", "ja", "ru"}
    for lang in expected_langs:
        entry = registry.entries.get(("greeting.palette", lang))
        assert entry is not None, f"greeting.palette missing for lang={lang!r}"
        assert isinstance(entry.text, list), f"greeting.palette must be list-typed for {lang!r}"
        assert len(entry.text) > 0, f"greeting.palette empty for {lang!r}"

    # en + id at verified, others at draft per lift-and-shift policy
    assert registry.entries[("greeting.palette", "en")].status == "verified"
    assert registry.entries[("greeting.palette", "id")].status == "verified"
    for lang in expected_langs - {"en", "id"}:
        entry = registry.entries[("greeting.palette", lang)]
        assert entry.status == "draft", (
            f"Non-Phase-2a lang {lang!r} must be lifted at status=draft, got {entry.status!r}"
        )


def test_task14_pick_greeting_reads_from_i18n_when_available():
    """`_pick_greeting` consumer reads from i18n loader (Task 14 wire-up)."""
    from modules.system_detection.sd_prompts import _pick_greeting

    # id: should return a phrase from the i18n entry
    phrase, code = _pick_greeting("id", seed="deterministic-test")
    assert code == "id"
    # Verify the phrase IS one of the loaded id palette entries
    registry = _get_registry()
    id_palette = registry.entries[("greeting.palette", "id")].text
    assert phrase in id_palette


def test_task14_pick_greeting_falls_back_to_legacy_when_i18n_empty(monkeypatch):
    """Defensive fallback — if i18n loader returns empty for both lang+en,
    use the legacy _GREETING_PALETTE dict (DEPRECATED — to be removed in Task 19)."""
    from modules.system_detection.sd_prompts import _pick_greeting, _GREETING_PALETTE

    # Force the i18n primary lookup to return empty
    monkeypatch.setattr(
        "modules.system_detection.sd_prompts._greeting_palette_from_i18n",
        lambda code: [],
    )

    phrase, code = _pick_greeting("id", seed="test")
    assert code == "id"
    # Falls back to legacy palette
    assert phrase in _GREETING_PALETTE["id"]


def test_task14_legacy_palette_still_present_strict_additive():
    """Strict-additive — _GREETING_PALETTE legacy dict NOT deleted in Task 14."""
    from modules.system_detection.sd_prompts import _GREETING_PALETTE
    expected_langs = {"id", "ms", "en", "fr", "de", "it", "pt", "es",
                      "vi", "th", "da", "zh", "ja", "ru"}
    assert set(_GREETING_PALETTE.keys()) == expected_langs


# ============================================================================
# Task 16 — RESCUE_SOFT_BRIDGE migration (Step 5)
# ============================================================================


def test_task16_schema_has_rescue_soft_bridge_key():
    registry = _get_registry()
    assert "natural_qual.rescue_soft_bridge" in registry.schema
    meta = registry.schema["natural_qual.rescue_soft_bridge"]
    assert "q" in meta.get("placeholders", []), "Schema must declare {q} placeholder"
    assert "en" in meta.get("required_for", [])
    assert "id" in meta.get("required_for", [])


def test_task16_render_rescue_message_reads_from_i18n():
    """Consumer reads from i18n loader and substitutes {q} placeholder."""
    from modules.service_agent.natural_qual.nq_policies import render_rescue_message
    out_en = render_rescue_message("en", "Could you confirm your role?")
    assert "Could you confirm your role?" in out_en
    assert out_en.startswith("To keep this moving")

    out_id = render_rescue_message("id", "Apakah Anda di Indonesia?")
    assert "Apakah Anda di Indonesia?" in out_id
    assert "Biar saya bisa lanjut bantu" in out_id


def test_task16_render_rescue_message_unknown_lang_falls_back_to_en():
    from modules.service_agent.natural_qual.nq_policies import render_rescue_message
    # Klingon — falls back to English (i18n runtime fallback + langid passthrough)
    out = render_rescue_message("klingon", "What's your timeline?")
    assert "What's your timeline?" in out
    assert "To keep this moving" in out  # English baseline template


def test_task16_all_14_legacy_langs_lifted():
    """All 14 langs from legacy RESCUE_SOFT_BRIDGE present in i18n."""
    registry = _get_registry()
    expected_langs = {"en", "id", "ms", "th", "vi", "da", "de", "es",
                      "fr", "it", "ja", "pt", "ru", "zh"}
    for lang in expected_langs:
        entry = registry.entries.get(("natural_qual.rescue_soft_bridge", lang))
        assert entry is not None, f"rescue_soft_bridge missing for lang={lang!r}"
        assert "{q}" in entry.text, f"Template for {lang!r} must contain {{q}} placeholder"


def test_task16_legacy_dict_still_present():
    """Strict-additive — RESCUE_SOFT_BRIDGE dict NOT deleted in Task 16."""
    from modules.service_agent.natural_qual.nq_policies import RESCUE_SOFT_BRIDGE
    assert len(RESCUE_SOFT_BRIDGE) == 14


# ============================================================================
# Task 15 — _OPENER_PALETTE + _BANNED_OPENERS migration (Step 4+6)
# ============================================================================


def test_task15_schema_has_opener_palette_and_banned_forms():
    registry = _get_registry()
    assert "opener.palette" in registry.schema
    assert "opener.banned_forms" in registry.schema
    assert registry.schema["opener.palette"].get("type") == "list"
    assert registry.schema["opener.banned_forms"].get("type") == "list"


def test_task15_opener_palette_all_10_legacy_langs_lifted():
    """Legacy _OPENER_PALETTE has 10 langs — all lifted at verified (en+id) or draft."""
    registry = _get_registry()
    legacy_langs = {"id", "en", "ms", "fr", "de", "th", "ru", "zh", "it", "ja"}
    for lang in legacy_langs:
        entry = registry.entries.get(("opener.palette", lang))
        assert entry is not None, f"opener.palette missing for {lang!r}"
        assert isinstance(entry.text, list)
        assert len(entry.text) > 0
    # en + id verified per Phase 2a
    assert registry.entries[("opener.palette", "en")].status == "verified"
    assert registry.entries[("opener.palette", "id")].status == "verified"


def test_task15_pt_es_vi_da_remain_missing_per_lift_and_shift_policy():
    """pt/es/vi/da NOT in legacy _OPENER_PALETTE → stay status=missing per policy."""
    registry = _get_registry()
    for lang in ("pt", "es", "vi", "da"):
        entry = registry.entries.get(("opener.palette", lang))
        # Either absent entirely OR present with status=missing
        if entry is not None:
            assert entry.status == "missing"


def test_task15_banned_forms_id_only():
    """Legacy _BANNED_OPENERS_BY_LANG has only id — lifted at verified."""
    registry = _get_registry()
    entry = registry.entries.get(("opener.banned_forms", "id"))
    assert entry is not None
    assert isinstance(entry.text, list)
    assert "baik" in [s.lower() for s in entry.text]
    assert "baiklah" in [s.lower() for s in entry.text]
    assert entry.status == "verified"


def test_task15_opener_guidance_block_reads_from_i18n():
    """SA opener guidance consumer now reads from i18n loader."""
    from modules.service_agent.sa_prompts import _opener_guidance_block
    block = _opener_guidance_block(
        language_code="id", language_name="Indonesian", recent_openers=[],
    )
    # Should contain the lifted id opener palette
    assert "Oke" in block or "Siap" in block or "Paham" in block
    # Banned-forms-id is "Baik"/"Baiklah" — should appear in NEVER-start-with line
    assert "Baik" in block


def test_task15_legacy_dicts_still_present():
    """Strict-additive — _OPENER_PALETTE + _BANNED_OPENERS_BY_LANG NOT deleted in Task 15."""
    from modules.service_agent.sa_prompts import _OPENER_PALETTE, _BANNED_OPENERS_BY_LANG
    assert "id" in _OPENER_PALETTE
    assert "en" in _OPENER_PALETTE
    assert "id" in _BANNED_OPENERS_BY_LANG


# ============================================================================
# Task 17 — picker labels (Step 7)
# ============================================================================


def test_task17_schema_has_4_picker_keys():
    """4 picker label keys: book_meeting, other_services, stay_label, switch_label."""
    registry = _get_registry()
    expected_keys = {
        "picker.book_meeting.label",
        "picker.other_services.label",
        "picker.stay_label",
        "picker.switch_label",
    }
    for key in expected_keys:
        assert key in registry.schema, f"Schema missing {key!r}"


def test_task17_stay_switch_have_placeholders():
    """stay_label needs {current_label}; switch_label needs {target_label}."""
    registry = _get_registry()
    stay_meta = registry.schema["picker.stay_label"]
    switch_meta = registry.schema["picker.switch_label"]
    assert "current_label" in stay_meta.get("placeholders", [])
    assert "target_label" in switch_meta.get("placeholders", [])


def test_task17_all_14_legacy_langs_lifted_picker():
    """All 14 legacy picker langs lifted across all 4 picker keys."""
    registry = _get_registry()
    legacy_langs = {"id", "en", "ms", "fr", "de", "it", "es", "pt",
                    "th", "ru", "vi", "da", "ja", "zh"}
    for key in ("picker.book_meeting.label", "picker.other_services.label",
                "picker.stay_label", "picker.switch_label"):
        for lang in legacy_langs:
            entry = registry.entries.get((key, lang))
            assert entry is not None, f"{key}[{lang}] missing"


def test_task17_book_meeting_label_id_substitutes_correctly():
    """Verify i18n rendering for picker.book_meeting.label[id]."""
    from modules.i18n import t
    result = t("picker.book_meeting.label", "id")
    assert result == "Jadwalkan meeting"


def test_task17_stay_switch_labels_substitute_placeholders():
    """Verify {current_label} and {target_label} placeholder substitution."""
    from modules.i18n import t
    stay = t("picker.stay_label", "id", current_label="WBS")
    switch = t("picker.switch_label", "id", target_label="EBS")
    assert stay == "Lanjut WBS"
    assert switch == "Pindah ke EBS"


# ============================================================================
# Task 18 — meeting surfaces (Step 8) — partial migration
# ============================================================================
# Migrated: build_meeting_footer + build_other_slot_label (2 of 3 surfaces).
# Deferred: build_meeting_picker_preamble (per-lang structural variants).


def test_task18_schema_has_meeting_keys():
    registry = _get_registry()
    assert "meeting.footer" in registry.schema
    assert "meeting.other_slot_label" in registry.schema


def test_task18_all_11_legacy_langs_lifted():
    """11 langs incl rm Romansh lifted into meeting.* entries."""
    registry = _get_registry()
    expected_langs = {"id", "en", "ms", "fr", "de", "it", "ru", "th",
                      "es", "pt", "rm"}
    for key in ("meeting.footer", "meeting.other_slot_label"):
        for lang in expected_langs:
            entry = registry.entries.get((key, lang))
            assert entry is not None, f"{key}[{lang}] missing"


def test_task18_meeting_footer_id_renders():
    """Verify i18n rendering for meeting.footer[id]."""
    from modules.i18n import t
    result = t("meeting.footer", "id")
    assert "tim Sales" in result
    assert "+62 21" in result


def test_task18_meeting_other_slot_label_id_renders():
    from modules.i18n import t
    assert t("meeting.other_slot_label", "id") == "Rekomendasi Slot Lainnya"


def test_task18_romansh_yaml_created():
    """Romansh (rm) Phase 1 follow-up — file created with meeting.* entries only."""
    registry = _get_registry()
    rm_footer = registry.entries.get(("meeting.footer", "rm"))
    rm_label = registry.entries.get(("meeting.other_slot_label", "rm"))
    assert rm_footer is not None
    assert rm_label is not None
    # Romansh content verifiable
    assert "inscunter" in rm_footer.text or "info@integrity-asia.com" in rm_footer.text


def test_task18_meeting_picker_preamble_deferred_to_phase1():
    """build_meeting_picker_preamble NOT in schema — explicitly deferred."""
    registry = _get_registry()
    assert "meeting.picker_preamble" not in registry.schema, (
        "build_meeting_picker_preamble migration deferred to Phase 1 per Task 18 scope "
        "decision (per-lang structural variants require careful refactor)"
    )


# ============================================================================
# Task 19 — Step 9 cleanup (partial deletion)
# ============================================================================
# Pragmatic Phase 0 scope: legacy if/elif chains in sd_service.py picker helpers
# + sd_meeting.py builders rendered dead code via early-return + inline safety
# fallback. Legacy palette dicts in sd_prompts.py/sa_prompts.py/nq_policies.py
# RETAINED as safety net per docs/modules/out_of_context.md Phase 0 limitations.
# Full dict deletion deferred to Phase 1 after production smoke verification.


def test_task19_picker_helpers_have_inline_safety_fallback():
    """Task 19 partial — picker label helpers in sd_service.py have inline English
    fallback instead of legacy if/elif chain reachable via execution."""
    import pathlib
    src = pathlib.Path("modules/system_detection/sd_service.py").read_text(encoding="utf-8")
    # Each helper has `except Exception: return "<inline English>"` pattern
    assert 'except Exception:\n        return "Schedule a meeting"' in src, (
        "_book_meeting_label must have inline safety fallback"
    )
    assert 'except Exception:\n        return "Other Services"' in src, (
        "_other_services_label must have inline safety fallback"
    )


def test_task19_meeting_helpers_have_inline_safety_fallback():
    """Task 19 partial — meeting builders in sd_meeting.py."""
    import pathlib
    src = pathlib.Path("modules/system_detection/sd_meeting.py").read_text(encoding="utf-8")
    assert 'return "Other Slot Recommendations"' in src
    assert "schedule a meeting" in src.lower()


def test_task19_legacy_dicts_retained_with_deprecation_markers():
    """Task 19 partial — legacy palette dicts kept as Phase 0 safety net.

    Per Phase 0 limitation, full dict deletion deferred to Phase 1. Each dict
    must have DEPRECATED comment marker for future cleanup discoverability.
    """
    import pathlib
    sd_prompts = pathlib.Path("modules/system_detection/sd_prompts.py").read_text(encoding="utf-8")
    sa_prompts = pathlib.Path("modules/service_agent/sa_prompts.py").read_text(encoding="utf-8")
    nq_policies = pathlib.Path("modules/service_agent/natural_qual/nq_policies.py").read_text(encoding="utf-8")

    assert "DEPRECATED 2026-05-13 (Task 14)" in sd_prompts
    assert "DEPRECATED 2026-05-13 (Task 15)" in sa_prompts
    assert "DEPRECATED 2026-05-13 (Task 16)" in nq_policies


def test_task18_legacy_helpers_still_present():
    """Strict-additive — build_meeting_footer + build_other_slot_label legacy
    if/elif chains NOT deleted in Task 18. Task 19 will sweep."""
    import pathlib
    src = pathlib.Path("modules/system_detection/sd_meeting.py").read_text(encoding="utf-8")
    # Both helpers still have their legacy if/elif chains
    assert 'if lang.startswith("id"):' in src
    assert "build_meeting_picker_preamble" in src  # picker_preamble untouched


def test_task17_consumer_source_uses_i18n_primary_path():
    """Source-inspection — sd_service.py consumers wired to read from i18n.

    Direct execution blocked by chroma coupling; source-level test confirms wire-up.
    """
    import pathlib
    src = pathlib.Path("modules/system_detection/sd_service.py").read_text(encoding="utf-8")
    # _book_meeting_label uses i18n
    assert 't("picker.book_meeting.label"' in src.replace("'", '"').replace("_t(", "t(")
    # _stay_switch_labels uses i18n
    assert "picker.stay_label" in src
    assert "picker.switch_label" in src
