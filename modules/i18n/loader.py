"""YAML loader + validator for i18n translations.

See docs/superpowers/specs/2026-05-13-ooc-response-engine-design.md §4.2 + §4.4.

Validation severity (4-tier per spec):
- CRITICAL — refuse to start (raises MissingKeyError on .load())
- WARN     — log + continue (missing-status, banned-form drift, word-count overflow)
- INFO     — log informational (baseline_hash mismatch auto-flips to stale_re_review)
- RUNTIME_FALLBACK — runtime-only, see registry.StringRegistry.t()
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import hashlib
import logging
import re
import yaml

from modules.i18n.registry import StringRegistry, StringEntry, MissingKeyError

log = logging.getLogger(__name__)

_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


@dataclass
class ValidationIssue:
    severity: str  # "CRITICAL" | "WARN" | "INFO"
    key: str
    lang: Optional[str]
    message: str


@dataclass
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def has_critical(self) -> bool:
        return any(i.severity == "CRITICAL" for i in self.issues)

    def critical_issues(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "CRITICAL"]

    def warn_issues(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "WARN"]

    def info_issues(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "INFO"]

    def raise_if_critical(self) -> None:
        crit = self.critical_issues()
        if crit:
            msgs = "\n".join(
                f"  [{i.severity}] {i.key} ({i.lang}): {i.message}" for i in crit
            )
            raise MissingKeyError(
                f"i18n validation CRITICAL ({len(crit)} issue(s)):\n{msgs}"
            )


@dataclass
class I18nLoader:
    """Loads schema + per-lang YAML, runs validation, returns StringRegistry."""

    base_dir: Path

    def _load_schema(self) -> dict[str, dict]:
        path = self.base_dir / "schema.yaml"
        if not path.exists():
            return {}
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _load_lang_file(self, lang: str) -> dict[str, dict]:
        path = self.base_dir / "strings" / f"{lang}.yaml"
        if not path.exists():
            return {}
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _list_lang_files(self) -> list[str]:
        strings_dir = self.base_dir / "strings"
        if not strings_dir.exists():
            return []
        return sorted(p.stem for p in strings_dir.glob("*.yaml"))

    @staticmethod
    def _extract_placeholders(text: str) -> set[str]:
        return set(_PLACEHOLDER_RE.findall(text))

    @staticmethod
    def _hash_baseline(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def validate(self) -> ValidationReport:
        """Run validation contract without mutating state.

        Returns a ValidationReport. CRITICAL issues fail .load(); WARN/INFO are
        logged but do not block.
        """
        report = ValidationReport()
        schema = self._load_schema()
        langs = self._list_lang_files()
        lang_data = {lang: self._load_lang_file(lang) for lang in langs}
        en_data = lang_data.get("en", {})

        for key, meta in schema.items():
            declared_placeholders = set(meta.get("placeholders") or [])
            required_for = set(meta.get("required_for") or [])
            is_list_typed = meta.get("type") == "list"

            for lang in required_for:
                entry_data = (lang_data.get(lang) or {}).get(key)

                # CRITICAL: required key entirely absent from required-lang YAML
                if entry_data is None:
                    report.issues.append(
                        ValidationIssue(
                            severity="CRITICAL",
                            key=key,
                            lang=lang,
                            message=f"Required key absent from {lang}.yaml",
                        )
                    )
                    continue

                status = entry_data.get("status", "missing")

                # WARN: required key present but status=missing (deploy-time visibility)
                if status == "missing":
                    report.issues.append(
                        ValidationIssue(
                            severity="WARN",
                            key=key,
                            lang=lang,
                            message="status=missing — translation needed",
                        )
                    )

                text = entry_data.get("text")
                # Placeholder check skipped when the entry won't render at runtime
                # (status=missing or deprecated → fallback to English).
                if text and not is_list_typed and status not in ("missing", "deprecated"):
                    # CRITICAL: placeholder mismatch between schema and YAML text
                    if isinstance(text, str):
                        actual = self._extract_placeholders(text)
                        extra = actual - declared_placeholders
                        missing = declared_placeholders - actual
                        if extra or missing:
                            report.issues.append(
                                ValidationIssue(
                                    severity="CRITICAL",
                                    key=key,
                                    lang=lang,
                                    message=(
                                        f"Placeholder mismatch — extra: {sorted(extra)}, "
                                        f"missing: {sorted(missing)}"
                                    ),
                                )
                            )

                # INFO: baseline_hash drift on verified non-en entries
                if status == "verified" and lang != "en":
                    expected_hash = entry_data.get("baseline_hash")
                    en_entry = en_data.get(key, {})
                    en_text = en_entry.get("text") or ""
                    if isinstance(en_text, str):
                        actual_hash = self._hash_baseline(en_text)
                        if expected_hash and expected_hash != actual_hash:
                            report.issues.append(
                                ValidationIssue(
                                    severity="INFO",
                                    key=key,
                                    lang=lang,
                                    message="baseline_hash mismatch — auto-flip to stale_re_review",
                                )
                            )
        return report

    def load(self) -> StringRegistry:
        """Run validation, refuse to start on CRITICAL, then build the registry.

        WARN-level issues are logged but do not block startup.
        INFO-level issues (baseline_hash drift) auto-flip status to stale_re_review.
        """
        report = self.validate()
        report.raise_if_critical()

        registry = StringRegistry()
        registry.schema = self._load_schema()

        # Load glossary if present (service_labels + field_labels + ui_terms).
        glossary_path = self.base_dir / "glossary.yaml"
        if glossary_path.exists():
            with open(glossary_path, encoding="utf-8") as f:
                gdata = yaml.safe_load(f) or {}
                registry.service_labels = gdata.get("service_labels") or {}
                registry.field_labels = gdata.get("field_labels") or {}
                registry.ui_terms = gdata.get("ui_terms") or {}

        # Auto-flip stale entries (INFO severity)
        stale_set = {
            (i.key, i.lang)
            for i in report.issues
            if "baseline_hash mismatch" in i.message
        }

        for lang in self._list_lang_files():
            for key, entry_data in self._load_lang_file(lang).items():
                status = entry_data.get("status", "missing")
                if (key, lang) in stale_set:
                    status = "stale_re_review"
                registry.entries[(key, lang)] = StringEntry(
                    text=entry_data.get("text"),
                    status=status,
                    reviewer=entry_data.get("reviewer"),
                    reviewed_date=entry_data.get("reviewed_date"),
                    ai_assisted=bool(entry_data.get("ai_assisted")),
                    baseline_hash=entry_data.get("baseline_hash"),
                )

        # Surface WARN issues at log level (don't block)
        for issue in report.warn_issues():
            log.warning(
                "i18n_validation_warn",
                extra={
                    "key": issue.key,
                    "lang": issue.lang,
                    "detail": issue.message,
                },
            )
        for issue in report.info_issues():
            log.info(
                "i18n_validation_info",
                extra={
                    "key": issue.key,
                    "lang": issue.lang,
                    "detail": issue.message,
                },
            )

        return registry
