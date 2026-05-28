"""OOC renderer — shape-aware rendering with bidi wrap + template_variant_for_lang.

Per spec docs/superpowers/specs/2026-05-13-ooc-response-engine-design.md §1.2 B4 + §2.2.

Shape pipelines:
    cold_start            → 1 paragraph from `ooc.{category}.cold_start`
    mid_flow_standard     → P1 + P2 (standard_with_field) + P3 (repose)
    mid_flow_high_stakes  → P1 + P2 + P3 + P4 (escalation)
    mid_flow_pre_data     → P1 + P2 (pre_data) + P3 (opt_in_continuation)
    escalation_handover   → ack + handover_contacts + resume_offer

Watchpoints addressed (per user):
- template_variant_for_lang lookup happens BEFORE per-lang YAML fallback
- auto_bidi_wrap_extracted_vars inserts U+2066/U+2069 markers correctly
"""
from __future__ import annotations
import logging
from typing import Optional

from modules.i18n import _get_registry, t
from modules.i18n.lint import bidi_wrap_for_rtl, is_rtl_lang

log = logging.getLogger(__name__)


# Composite shape definitions. "__P1_PER_CATEGORY" is a sentinel resolved per
# decision.label at render time.
_COMPOSITE_KEYS: dict[str, list[str]] = {
    "mid_flow_standard": [
        "__P1_PER_CATEGORY",
        "ooc.midflow.p2_standard_with_field",
        "ooc.midflow.p3_repose",
    ],
    "mid_flow_high_stakes": [
        "__P1_PER_CATEGORY",
        "ooc.midflow.p2_standard_with_field",
        "ooc.midflow.p3_repose",
        "ooc.high_stakes.p4_escalation",
    ],
    "mid_flow_pre_data": [
        "__P1_PER_CATEGORY",
        "ooc.midflow.p2_pre_data",
        "ooc.midflow.p3_opt_in_continuation",
    ],
    "escalation_handover": [
        "ooc.escalation.acknowledgment",
        "ooc.escalation.handover_contacts",
        "ooc.escalation.resume_offer",
    ],
}

# Routing-asset placeholders that must be bidi-wrapped in RTL flows
# (spec §4.11 + Constraint #6 immutability).
_ROUTING_ASSET_VARS = frozenset({
    "indo_email", "indo_phone", "my_sg_email", "my_sg_phone",
    "th_vn_email", "th_vn_phone", "business_hours",
    "partnership_url", "freelancer_url", "mystery_shopper_url",
    "careers_url", "company_profile_url",
})


class OOCRenderer:
    """Shape-aware renderer; consumes i18n loader."""

    def __init__(self):
        self.registry = _get_registry()

    # ---------------------------------------------------------------- schema helpers

    def _get_schema_for(self, key: str) -> dict:
        return self.registry.schema.get(key, {}) or {}

    def _resolve_key_with_variant(self, key: str, lang: str) -> str:
        """Apply template_variant_for_lang override BEFORE per-lang YAML fallback.

        Per spec D6 row 11: schema field `template_variant_for_lang: {lang: variant_name}`
        causes the renderer to look up `<key>_<variant>` in the same lang's YAML if it
        exists. Falls through to base key otherwise.
        """
        schema = self._get_schema_for(key)
        variant_map = schema.get("template_variant_for_lang") or {}
        if lang in variant_map:
            variant_key = f"{key}_{variant_map[lang]}"
            if self.registry.has(variant_key, lang):
                return variant_key
            # If variant declared but YAML entry missing, log + fall through
            log.warning(
                "ooc_renderer_variant_declared_but_yaml_missing",
                extra={
                    "key": key,
                    "lang": lang,
                    "expected_variant_key": variant_key,
                },
            )
        return key

    # ---------------------------------------------------------------- bidi wrap

    def _wrap_vars_for_rtl(
        self,
        template_vars: dict,
        category: str,
        lang: str,
    ) -> dict:
        """Apply bidi-wrap to vars when rendering in an RTL lang.

        Two-tier wrap policy (spec §4.11 + D6 row 10):
        1. Routing-asset placeholders ALWAYS wrap in RTL flows (Latin-script immutable)
        2. Extracted-mention/hint vars wrap when category schema has
           `auto_bidi_wrap_extracted_vars: true`
        """
        if not is_rtl_lang(lang):
            return template_vars

        wrapped = dict(template_vars)

        # Tier 1: routing assets
        for var_name in _ROUTING_ASSET_VARS:
            if var_name in wrapped and wrapped[var_name]:
                wrapped[var_name] = bidi_wrap_for_rtl(str(wrapped[var_name]), lang)

        # Tier 2: extracted vars (per-category opt-in)
        category_schema = self._get_schema_for(f"ooc.{category}.cold_start") or {}
        if category_schema.get("auto_bidi_wrap_extracted_vars"):
            for var_name in ("mentioned_service", "extracted_mention"):
                if var_name in wrapped and wrapped[var_name]:
                    wrapped[var_name] = bidi_wrap_for_rtl(str(wrapped[var_name]), lang)

        return wrapped

    # ---------------------------------------------------------------- render

    def _render_single(self, key: str, lang: str, vars: dict) -> str:
        """Render one key with variant resolution + format substitution."""
        actual_key = self._resolve_key_with_variant(key, lang)
        return t(actual_key, lang, **vars)

    def render(
        self,
        category: str,
        shape: str,
        lang: str,
        template_vars: dict,
    ) -> str:
        """Render the OOC response message.

        Args:
            category: OOCCategory value (e.g., "OOC-PARTNERSHIP")
            shape: ShapeUsed value (e.g., "cold_start", "mid_flow_standard")
            lang: 2-char language code
            template_vars: placeholder substitution values

        Returns rendered string. Raises ValueError on unknown shape.
        """
        wrapped_vars = self._wrap_vars_for_rtl(template_vars, category, lang)

        if shape == "cold_start":
            return self._render_single(
                f"ooc.{category}.cold_start", lang, wrapped_vars
            )

        composite = _COMPOSITE_KEYS.get(shape)
        if composite is None:
            raise ValueError(f"Unknown shape: {shape!r}")

        paragraphs: list[str] = []
        for key in composite:
            if key == "__P1_PER_CATEGORY":
                actual_key = f"ooc.{category}.midflow.p1"
            else:
                actual_key = key
            paragraphs.append(self._render_single(actual_key, lang, wrapped_vars))

        return "\n\n".join(paragraphs)
