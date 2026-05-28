from __future__ import annotations

import logging
from typing import Optional

import pydantic

from .ooc_types import (
    OOCDecision,
    OOCResult,
    OOCContext,
    OOCAuditMetadata,
)
from .ooc_policies import (
    OOCPolicies,
    cheap_precheck,
    is_locale_allowed,
    FREELANCE_KEYWORDS,
    PARTNERSHIP_KEYWORDS,
    keyword_hits,
    build_reply,
)
from .ooc_classifier import OOCClassifier
from .ooc_renderer import OOCRenderer
from core.app_config import Config

log = logging.getLogger(__name__)


# Routing assets (immutable per Constraint #6). Production may override via
# `OOCService(routing_assets=...)` injection. Defaults centralized here so
# all OOC paths use identical contact information.
ROUTING_ASSETS: dict[str, str] = {
    "indo_email": "contact@integrity-asia.com",
    "indo_phone": "+62 21 7822 3691",
    "my_sg_email": "my-sg@integrity-asia.com",
    "my_sg_phone": "+60 3 1234 5678",
    "th_vn_email": "th-vn@integrity-asia.com",
    "th_vn_phone": "+66 2 1234 5678",
    "business_hours": "Mon-Fri 09:00-18:00 WIB",
    "mystery_shopper_url": "https://integrity-asia.com/mystery-shopper",
    "careers_url": "https://integrity-asia.com/careers",
    "company_profile_url": "https://integrity-asia.com/",
}

def _no(reason: str = "no_match") -> OOCDecision:
    return OOCDecision(
        yes=False,
        label="none",
        confidence=0.0,
        reason=reason,
    )

class OOCService:
    """
    Mode keyword:
      - cheap_precheck
      - compare fh vs ph
      - if tie/ambiguous => not triggered
    """

    def __init__(self, policies: OOCPolicies | None = None):
        self.policies = policies or OOCPolicies()

    def _build_keyword_result(self, label: str, fh: int, ph: int, language_code: str | None) -> OOCResult:
        p = self.policies
        msg = build_reply(
            label,
            language_code=language_code,
            freelancer_url=p.freelancer_url,
            partner_url=p.partner_url,
        )
        return OOCResult(
            triggered=True,
            decision=OOCDecision(
                yes=True,
                label=label,          # "freelance" | "partnership"
                confidence=1.0,
                reason=f"keyword_match fh={fh} ph={ph}",
            ),
            route="ooc_agent",
            message=msg,
            prompt_applied=None,
            debug={"mode": "keyword", "fh": fh, "ph": ph, "language_code": language_code},
        )

    def _classify_keyword_only(self, text: str, language_code: str | None) -> OOCResult:
        p = self.policies
        fh = keyword_hits(text, FREELANCE_KEYWORDS)
        ph = keyword_hits(text, PARTNERSHIP_KEYWORDS)

        if fh > ph and fh >= p.min_keyword_hits:
            return self._build_keyword_result("freelance", fh, ph, language_code)

        if ph > fh and ph >= p.min_keyword_hits:
            return self._build_keyword_result("partnership", fh, ph, language_code)

        return OOCResult(
            triggered=False,
            decision=_no("keyword_ambiguous"),
            route="ooc_agent",
            message="",
            prompt_applied=None,
            debug={"mode": "keyword", "fh": fh, "ph": ph, "language_code": language_code},
        )

    def classify(self, *, user_text: str, language_code: str | None = None) -> OOCResult:
        p = self.policies

        if not p.enabled:
            return OOCResult(triggered=False, decision=_no("disabled"), route="ooc_agent")

        if not is_locale_allowed(p, language_code):
            return OOCResult(triggered=False, decision=_no("locale_not_allowed"), route="ooc_agent")

        if not cheap_precheck(user_text, p):
            return OOCResult(triggered=False, decision=_no("no_keyword_hit"), route="ooc_agent")

        # mode switch
        if p.mode == "keyword":
            return self._classify_keyword_only(user_text, language_code)

        # sementara: kalau kamu belum aktifkan hybrid/llm, fallback ke keyword saja biar aman
        return self._classify_keyword_only(user_text, language_code)

    def maybe_handle(self, *, user_text: str, language_code: str | None = None) -> Optional[OOCResult]:
        r = self.classify(user_text=user_text, language_code=language_code)
        return r if r.triggered else None

    # ========================================================================
    # Stage 0 — Layer B pipeline (per spec §1.2 B1-B5)
    # ========================================================================

    def _get_handle_components(self):
        """Lazy-init classifier + renderer + cfg.

        Lazy because OOCService.__init__ has a long-standing contract of taking
        OOCPolicies; adding required deps would break existing callers. Lazy-init
        also lets tests inject mocks via patching `_get_handle_components`.
        """
        cfg = Config()
        classifier = OOCClassifier(mode=cfg.OOC_MODE)
        renderer = OOCRenderer()
        return cfg, classifier, renderer

    def handle(
        self,
        ctx: OOCContext,
        routing_assets: Optional[dict[str, str]] = None,
    ) -> Optional[OOCResult]:
        """Layer B pipeline — classify, gate, shape, render, assemble.

        Returns OOCResult when message is OOC; returns None when message
        passes through to the existing dispatcher (Constraint #4 in-scope
        protection, low LLM confidence, no match, etc.).
        """
        cfg, classifier, renderer = self._get_handle_components()
        assets = routing_assets or ROUTING_ASSETS

        # B1: classify
        decision = classifier.classify(
            text=ctx.user_text,
            language=ctx.user_detected_language,
            active_service=ctx.active_service,
        )

        if not decision.yes:
            return None

        # B2: consecutive-OOC escalation gate (per spec §1.2 + §7.2 row 3)
        if ctx.previously_seen_OOC_in_session + 1 >= cfg.OOC_ESCALATION_THRESHOLD:
            return self._render_escalation(
                ctx=ctx, decision=decision, renderer=renderer, assets=assets
            )

        # B3: determine shape (4 branches — 5th is escalation_handover returned at B2)
        if ctx.active_service is None:
            shape = "cold_start"
        elif ctx.pre_data:
            # pre_data overrides high_stakes per spec Q#3 refinement
            shape = "mid_flow_pre_data"
        elif ctx.high_stakes_intake:
            shape = "mid_flow_high_stakes"
        else:
            shape = "mid_flow_standard"

        # B4: render
        template_vars = self._build_template_vars(ctx, decision, assets)
        try:
            message = renderer.render(
                category=decision.label,
                shape=shape,
                lang=ctx.user_detected_language,
                template_vars=template_vars,
            )
        except Exception as e:
            # Render failure should not crash the request — fall back to English.
            log.error(
                "ooc_render_failure",
                extra={
                    "category": decision.label,
                    "shape": shape,
                    "lang": ctx.user_detected_language,
                    "error": str(e),
                },
            )
            message = renderer.render(
                category=decision.label,
                shape=shape,
                lang="en",
                template_vars=template_vars,
            )

        # B5: assemble result
        return OOCResult(
            message=message,
            category=decision.label,
            shape_used=shape,
            language_used=ctx.user_detected_language,
            set_escalation_suppression=False,
            streak_classification="user_ooc",
            audit_metadata=self._build_audit_metadata(ctx, decision, shape=shape),
            # Legacy fields preserved for backward-compat callers
            triggered=True,
            decision=decision,
            route="out_of_context_agent",
        )

    # ------------------------------------------------------------------ helpers

    def _build_template_vars(
        self,
        ctx: OOCContext,
        decision: OOCDecision,
        assets: dict[str, str],
    ) -> dict:
        """Assemble template variable dict for renderer."""
        from modules.i18n import _get_registry

        registry = _get_registry()
        vars: dict = dict(assets)

        # Service + field labels (None when no active service)
        if ctx.active_service:
            label = registry.service_label(ctx.active_service, ctx.user_detected_language)
            vars["active_service_label"] = label or ""
        else:
            vars["active_service_label"] = ""

        if ctx.current_field_id:
            field_label = registry.field_label(
                ctx.current_field_id, ctx.user_detected_language
            )
            vars["current_field_label"] = field_label or ""
        else:
            vars["current_field_label"] = ""

        vars["last_question"] = ctx.last_question_text or ""

        # Polymorphic extracted vars (per spec §7.5)
        vars["mentioned_service"] = decision.extracted_mention or ""
        vars["user_field_hint"] = decision.extracted_hint or "[Your Field]"
        vars["engagement_reference"] = (
            decision.extracted_hint
            or "[Your Engagement / Project Reference if available]"
        )

        # Pillar block (rendered in target lang via i18n)
        try:
            vars["pillar_block"] = registry.t(
                "ooc.service.taxonomy.pillar_block", ctx.user_detected_language
            )
        except Exception as e:
            log.warning("ooc_pillar_block_render_failure", extra={"error": str(e)})
            vars["pillar_block"] = ""

        # OOC_FREELANCER_URL + OOC_PARTNER_URL come from env (Config)
        cfg = Config()
        vars.setdefault("freelancer_url", cfg.OOC_FREELANCER_URL)
        vars.setdefault("partnership_url", cfg.OOC_PARTNER_URL)

        return vars

    def _build_audit_metadata(
        self,
        ctx: OOCContext,
        decision: OOCDecision,
        shape: str,
    ) -> OOCAuditMetadata:
        """Build typed OOCAuditMetadata. ValidationError logs at ERROR + raw_data.

        Per spec Refinement #4 + cross-cutting note #1: pydantic ValidationError
        on audit payload MUST log at error severity AND include raw_data for
        forensic context. Silent degradation = undetected schema drift.
        """
        raw_data = {
            "classifier_confidence": decision.confidence,
            "classifier_mode": decision.classifier_mode,
            "extracted_mention": decision.extracted_mention,
            "extracted_hint": decision.extracted_hint,
            "ooc_excursion_count_post": ctx.previously_seen_OOC_in_session + 1,
            "previous_categories_chain": list(ctx.previous_user_ooc_categories),
            "raw_detected_language": ctx.raw_detected_language,
            "raw_detection_confidence": ctx.raw_detection_confidence,
            "effective_language_diverged_from_raw": (
                ctx.user_detected_language != ctx.raw_detected_language
            ),
            "pre_data": ctx.pre_data,
            "high_stakes_intake": ctx.high_stakes_intake,
            "active_service": ctx.active_service,
            "bidi_wrap_applied": ctx.user_detected_language in {"ar", "he", "fa", "ur"},
        }
        try:
            return OOCAuditMetadata(**raw_data)
        except pydantic.ValidationError as e:
            log.error(
                "OOCAuditMetadata validation failed",
                extra={"error": str(e), "raw_data_repr": repr(raw_data)},
            )
            # Construct minimal-valid fallback. classifier_mode + confidence are required.
            safe_conf = max(0.0, min(1.0, decision.confidence))
            return OOCAuditMetadata(
                classifier_confidence=safe_conf,
                classifier_mode=decision.classifier_mode,
                trigger="audit_metadata_validation_fallback",
            )

    def _render_escalation(
        self,
        ctx: OOCContext,
        decision: OOCDecision,
        renderer: OOCRenderer,
        assets: dict[str, str],
    ) -> OOCResult:
        """B2 escalation handover (system-meta turn)."""
        template_vars = self._build_template_vars(ctx, decision, assets)
        try:
            message = renderer.render(
                category="ESCALATION-CONSECUTIVE-OOC",
                shape="escalation_handover",
                lang=ctx.user_detected_language,
                template_vars=template_vars,
            )
        except Exception as e:
            log.error(
                "ooc_escalation_render_failure",
                extra={"lang": ctx.user_detected_language, "error": str(e)},
            )
            message = renderer.render(
                category="ESCALATION-CONSECUTIVE-OOC",
                shape="escalation_handover",
                lang="en",
                template_vars=template_vars,
            )

        return OOCResult(
            message=message,
            category="ESCALATION-CONSECUTIVE-OOC",
            shape_used="escalation_handover",
            language_used=ctx.user_detected_language,
            set_escalation_suppression=True,
            streak_classification="system_meta",
            audit_metadata=OOCAuditMetadata(
                classifier_confidence=decision.confidence,
                classifier_mode=decision.classifier_mode,
                trigger="consecutive_ooc_escalation",
                streak_length=ctx.previously_seen_OOC_in_session,
                pre_data=ctx.pre_data,
                high_stakes_intake=ctx.high_stakes_intake,
                active_service=ctx.active_service,
            ),
            triggered=True,
            decision=decision,
            route="out_of_context_agent",
        )