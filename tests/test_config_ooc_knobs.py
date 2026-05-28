"""Tests for OOC engine env knobs added in Stage 0 (2026-05-13).

Per project memory feedback_dotenv_override.md: tests must read Config defaults
as they are loaded from the current .env, NOT mutate os.environ at test time.
load_dotenv(override=True) at module import clobbers process env, so monkeypatch
on os.environ won't take effect without a Config re-import.
"""
from core.app_config import Config


def test_ooc_agent_enabled_default():
    cfg = Config()
    assert cfg.OOC_AGENT_ENABLED is True


def test_ooc_mode_default_hybrid():
    cfg = Config()
    assert cfg.OOC_MODE == "hybrid"


def test_ooc_escalation_threshold_default():
    cfg = Config()
    assert cfg.OOC_ESCALATION_THRESHOLD == 3


def test_ooc_escalation_suppression_turns_default():
    cfg = Config()
    assert cfg.OOC_ESCALATION_SUPPRESSION_TURNS == 3


def test_ooc_llm_confidence_floor_default():
    cfg = Config()
    assert cfg.OOC_LLM_CONFIDENCE_FLOOR == 0.6


def test_ooc_catchall_floor_default():
    cfg = Config()
    assert cfg.OOC_CATCHALL_FLOOR == 0.7


def test_ooc_keyword_confidence_default():
    cfg = Config()
    assert cfg.OOC_KEYWORD_CONFIDENCE == 0.95


def test_ooc_lang_detection_floor_default():
    cfg = Config()
    assert cfg.OOC_LANG_DETECTION_FLOOR == 0.85


def test_ooc_min_keyword_hits_default():
    cfg = Config()
    assert cfg.OOC_MIN_KEYWORD_HITS == 1


def test_ooc_min_text_len_default():
    cfg = Config()
    assert cfg.OOC_MIN_TEXT_LEN == 3


def test_ooc_high_stakes_services_contains_four_default_entries():
    cfg = Config()
    assert isinstance(cfg.OOC_HIGH_STAKES_SERVICES, tuple)
    assert "corporate_fraud_investigation" in cfg.OOC_HIGH_STAKES_SERVICES
    assert "insurance_claim_investigation" in cfg.OOC_HIGH_STAKES_SERVICES
    assert "asset_tracing" in cfg.OOC_HIGH_STAKES_SERVICES
    assert "skip_tracing" in cfg.OOC_HIGH_STAKES_SERVICES
    assert len(cfg.OOC_HIGH_STAKES_SERVICES) == 4


def test_ooc_allowed_locales_empty_default():
    cfg = Config()
    assert cfg.OOC_ALLOWED_LOCALES == ()


def test_ooc_posthoc_classifier_disabled_default():
    cfg = Config()
    assert cfg.OOC_POSTHOC_CLASSIFIER_ENABLED is False


def test_ooc_posthoc_classifier_sample_rate_default():
    cfg = Config()
    assert cfg.OOC_POSTHOC_CLASSIFIER_SAMPLE_RATE == 0.1


def test_ooc_posthoc_classifier_mode_default():
    cfg = Config()
    assert cfg.OOC_POSTHOC_CLASSIFIER_MODE == "keyword"


def test_ooc_high_stakes_services_is_tuple_not_list():
    # Tuple is immutable — prevents accidental mutation in service code.
    cfg = Config()
    assert isinstance(cfg.OOC_HIGH_STAKES_SERVICES, tuple)


def test_ooc_freelancer_url_default():
    cfg = Config()
    assert cfg.OOC_FREELANCER_URL == "https://www.integrity-indonesia.com/freelancer/"


def test_ooc_partner_url_default():
    cfg = Config()
    assert cfg.OOC_PARTNER_URL == "https://www.integrity-indonesia.com/partner/"


def test_full_ooc_knob_set_count_matches_spec():
    # Spec §6.3 requires 17 OOC env knobs in Config dataclass.
    cfg = Config()
    ooc_fields = [name for name in dir(cfg) if name.startswith("OOC_") and not callable(getattr(cfg, name))]
    assert len(ooc_fields) == 17, f"Expected 17 OOC fields per spec §6.3, found {len(ooc_fields)}: {ooc_fields}"
