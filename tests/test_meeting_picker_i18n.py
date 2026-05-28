"""Unit tests for the meeting-picker i18n helpers.

Run (pytest available):
    python -m pytest tests/test_meeting_picker_i18n.py -v

Run (stdlib only, no pytest):
    python tests/test_meeting_picker_i18n.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


# --- build_other_slot_label ---

def test_other_slot_label_all_languages():
    from modules.system_detection.sd_meeting import build_other_slot_label
    assert build_other_slot_label("id") == "Rekomendasi Slot Lainnya"
    assert build_other_slot_label("ms") == "Cadangan Slot Lain"
    assert build_other_slot_label("en") == "Other Slot Recommendations"
    assert build_other_slot_label("fr") == "Autres créneaux proposés"
    assert build_other_slot_label("de") == "Weitere Terminvorschläge"
    assert build_other_slot_label("it") == "Altri orari proposti"
    assert build_other_slot_label("rm") == "Auters propostas d'uras"
    assert build_other_slot_label("ru") == "Другие варианты времени"
    assert build_other_slot_label("th") == "ตัวเลือกเวลาอื่น"
    assert build_other_slot_label("es") == "Otras franjas horarias"
    assert build_other_slot_label("pt") == "Outros horários sugeridos"


def test_other_slot_label_prefix_match():
    from modules.system_detection.sd_meeting import build_other_slot_label
    assert build_other_slot_label("id-ID") == "Rekomendasi Slot Lainnya"
    assert build_other_slot_label("en-US") == "Other Slot Recommendations"
    assert build_other_slot_label("fr-CH") == "Autres créneaux proposés"


def test_other_slot_label_unknown_falls_back_to_english():
    from modules.system_detection.sd_meeting import build_other_slot_label
    assert build_other_slot_label("zh-CN") == "Other Slot Recommendations"
    assert build_other_slot_label("ja-JP") == "Other Slot Recommendations"
    assert build_other_slot_label(None) == "Other Slot Recommendations"
    assert build_other_slot_label("") == "Other Slot Recommendations"


# --- build_meeting_picker_preamble ---

def test_preamble_english_has_both_placeholders():
    from modules.system_detection.sd_meeting import build_meeting_picker_preamble
    out = build_meeting_picker_preamble("en",
        service_label="Background Check", nickname="Alice")
    assert "Background Check" in out
    assert "Alice" in out
    assert out.count(". ") >= 1
    assert "\n" not in out


def test_preamble_indonesian_has_both_placeholders():
    from modules.system_detection.sd_meeting import build_meeting_picker_preamble
    out = build_meeting_picker_preamble("id-ID",
        service_label="EBS", nickname="Budi")
    assert "EBS" in out
    assert "Budi" in out
    assert "\n" not in out


def test_preamble_drops_nickname_when_absent():
    from modules.system_detection.sd_meeting import build_meeting_picker_preamble
    out = build_meeting_picker_preamble("en",
        service_label="EBS", nickname=None)
    assert "None" not in out
    assert ", ." not in out and ",." not in out


def test_preamble_drops_service_when_absent():
    from modules.system_detection.sd_meeting import build_meeting_picker_preamble
    out = build_meeting_picker_preamble("en",
        service_label=None, nickname="Alice")
    assert "Alice" in out
    assert "\n" not in out


def test_preamble_unknown_language_falls_back_to_english():
    from modules.system_detection.sd_meeting import build_meeting_picker_preamble
    out_en = build_meeting_picker_preamble("en",
        service_label="EBS", nickname="Alice")
    out_zh = build_meeting_picker_preamble("zh-CN",
        service_label="EBS", nickname="Alice")
    assert out_en == out_zh
    out_none = build_meeting_picker_preamble(None,
        service_label="EBS", nickname="Alice")
    assert out_en == out_none


def test_preamble_all_eleven_languages_smoke():
    from modules.system_detection.sd_meeting import build_meeting_picker_preamble
    for prefix in ["id", "ms", "en", "fr", "de", "it", "rm", "ru", "th", "es", "pt"]:
        out = build_meeting_picker_preamble(prefix,
            service_label="EBS", nickname="Alice")
        assert out, f"{prefix}: empty output"
        assert "\n" not in out, f"{prefix}: contains line break"
        assert "EBS" in out, f"{prefix}: service missing"
        assert "Alice" in out, f"{prefix}: nickname missing"


def test_preamble_prefix_match_id_vs_id_id():
    from modules.system_detection.sd_meeting import build_meeting_picker_preamble
    id_out = build_meeting_picker_preamble("id", service_label="X", nickname="Y")
    id_id_out = build_meeting_picker_preamble("id-ID", service_label="X", nickname="Y")
    assert id_out == id_id_out


# --- build_meeting_choices_now include_other kwarg ---

def _availability_mock(first_date=None, second_date=None, **_kwargs):
    """Dynamic mock: return populated slots for whichever dates the caller asks for.
    Slot format must be 'HH:MM-HH:MM' range per _SLOT_RANGE_RE."""
    slots = ["09:00-10:00", "10:00-11:00", "11:00-12:00", "14:00-15:00", "15:00-16:00"]
    days = []
    if first_date:
        days.append({"date": first_date, "slots": slots})
    if second_date:
        days.append({"date": second_date, "slots": slots})
    return {"available_slots": days}


def test_build_meeting_choices_now_default_includes_other():
    from unittest.mock import patch
    with patch("modules.system_detection.meeting_arrangement.ma_service.fetch_user_profile",
               return_value={"timezone": "Asia/Jakarta", "email": "u@example.com"}), \
         patch("modules.system_detection.meeting_arrangement.ma_service.fetch_sales_availability",
               side_effect=_availability_mock), \
         patch("modules.system_detection.meeting_arrangement.ma_service._build_existing_meeting_warning",
               return_value=None):
        from modules.system_detection.meeting_arrangement.ma_service import build_meeting_choices_now
        result = build_meeting_choices_now(
            session_id="s1", website_id="w1", token_id=None,
            service_label="EBS", sales_email="sales@example.com",
            sales_name="Alice", language_name="English", language_code="en",
            user_nick="Bob", is_first_turn=True,
        )
        values = [c["value"] for c in result.get("choices", [])]
        assert "OTHER_PICKED_SLOT" in values, (
            f"default call should include OTHER_PICKED_SLOT; got {values}"
        )


def test_build_meeting_choices_now_include_other_false_omits_choice():
    from unittest.mock import patch
    with patch("modules.system_detection.meeting_arrangement.ma_service.fetch_user_profile",
               return_value={"timezone": "Asia/Jakarta", "email": "u@example.com"}), \
         patch("modules.system_detection.meeting_arrangement.ma_service.fetch_sales_availability",
               side_effect=_availability_mock), \
         patch("modules.system_detection.meeting_arrangement.ma_service._build_existing_meeting_warning",
               return_value=None):
        from modules.system_detection.meeting_arrangement.ma_service import build_meeting_choices_now
        result = build_meeting_choices_now(
            session_id="s1", website_id="w1", token_id=None,
            service_label="EBS", sales_email="sales@example.com",
            sales_name="Alice", language_name="English", language_code="en",
            user_nick="Bob", is_first_turn=True,
            include_other=False,
        )
        values = [c["value"] for c in result.get("choices", [])]
        assert "OTHER_PICKED_SLOT" not in values, (
            f"include_other=False should omit OTHER_PICKED_SLOT; got {values}"
        )
        assert any(v != "OTHER_PICKED_SLOT" for v in values), (
            f"include_other=False should still yield slot choices; got {values}"
        )


def test_boundary_is_count_ge_limit():
    """A1+B1 math: limit=2, click 1 → non-boundary, click 2 → boundary."""
    def compute(prev_count, limit):
        count = prev_count + 1
        return count, (count >= limit)
    count, boundary = compute(0, 2)
    assert count == 1 and boundary is False
    count, boundary = compute(1, 2)
    assert count == 2 and boundary is True
    count, boundary = compute(0, 1)
    assert count == 1 and boundary is True


if __name__ == "__main__":
    failures = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS: {name}")
            except AssertionError as e:
                print(f"FAIL: {name}: {e}")
                failures += 1
            except Exception as e:
                print(f"ERROR: {name}: {type(e).__name__}: {e}")
                failures += 1
    if failures:
        sys.exit(1)
    print(f"\nAll tests passed.")
