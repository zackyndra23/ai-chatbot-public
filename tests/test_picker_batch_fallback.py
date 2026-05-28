"""Unit tests for picker batch logic — covers the 2026-05-08 bug fix where
empty preferred (only 'General' + non-flow services) caused batch 0 to show
only 'Layanan Lainnya' instead of actual service choices.

Run (stdlib only, no pytest):
    python tests/test_picker_batch_fallback.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


# ---------- Fix #1: _map_related_service_to_value_code with short labels ----------

def test_map_short_label_parallel_trading_resolves():
    """Bug case: chunk metadata 'Parallel Trading' (short label) was unresolvable
    because SERVICE_LABEL_CODE_MAP has 'Parallel Trading Investigation' (long).
    Fix #1: also check SERVICE_VALUE_CODE_MAP (short → value_code)."""
    from modules.system_detection.sd_service import _map_related_service_to_value_code
    vc, lbl = _map_related_service_to_value_code("Parallel Trading")
    assert vc == "parallel_trading_investigation", f"got {vc!r}"
    assert lbl  # display label resolved


def test_map_canonical_label_still_works():
    """Sanity: canonical long-form labels still resolve."""
    from modules.system_detection.sd_service import _map_related_service_to_value_code
    vc, lbl = _map_related_service_to_value_code("Whistleblowing System")
    assert vc == "whistleblowing_system", f"got {vc!r}"


def test_map_unknown_label_returns_empty():
    """Service name not in any map returns empty tuple — no crash."""
    from modules.system_detection.sd_service import _map_related_service_to_value_code
    vc, lbl = _map_related_service_to_value_code("Some Random Unknown Service")
    assert vc == "" and lbl == ""


# ---------- Fix #2: unified paginator covers empty-preferred case ----------

def test_bug_case_general_plus_parallel_trading_no_more_layanan_lainnya_alone():
    """Bug: related_services = ['General', 'Parallel Trading'] → batch 0 had
    ONLY 'Layanan Lainnya' button. Fix: should show actual services."""
    from modules.system_detection.sd_service import _build_related_service_batch_choices
    result = _build_related_service_batch_choices(
        related_services=["General", "Parallel Trading"],
        language_code="id",
        batch_index=0,
        batch_size=5,
    )
    choices = result["choices"]
    # At least 1 actual service (not just the RS_OTHER_BATCH button)
    actual_services = [c for c in choices if not c["value"].startswith("RS_OTHER_BATCH_")]
    assert len(actual_services) >= 1, f"batch 0 must have actual services, got {choices!r}"
    # Parallel Trading should be present (now that fix #1 resolves it)
    pt_present = any("parallel_trading" in (c.get("value") or "").lower() for c in actual_services)
    assert pt_present, f"Parallel Trading should be in batch 0, got {[c.get('value') for c in choices]}"


def test_batch_0_full_5_services_when_preferred_small():
    """When preferred has only 1 service, batch 0 should fill up to 5 from catalog."""
    from modules.system_detection.sd_service import _build_related_service_batch_choices
    result = _build_related_service_batch_choices(
        related_services=["General", "Parallel Trading"],  # → preferred = [PTI]
        language_code="id",
        batch_index=0,
        batch_size=5,
    )
    choices = result["choices"]
    actual = [c for c in choices if not c["value"].startswith("RS_OTHER_BATCH_")]
    assert len(actual) == 5, f"batch 0 should have 5 actual services, got {len(actual)}"


def test_last_batch_no_other_services_button():
    """Last batch should NOT have 'Layanan Lainnya' button."""
    from modules.system_detection.sd_service import _build_related_service_batch_choices
    # Get total_batches first by querying batch 0
    info = _build_related_service_batch_choices(
        related_services=["General"],
        language_code="id",
        batch_index=0,
        batch_size=5,
    )
    total = info["total_batches"]
    assert total >= 2, f"need ≥2 batches for this test, got {total}"

    # Now query the last batch
    last = _build_related_service_batch_choices(
        related_services=["General"],
        language_code="id",
        batch_index=total - 1,
        batch_size=5,
    )
    has_more_button = any(
        (c.get("value") or "").startswith("RS_OTHER_BATCH_") for c in last["choices"]
    )
    assert not has_more_button, f"last batch must NOT have RS_OTHER_BATCH button, got {last['choices']!r}"


def test_middle_batch_has_other_services_button():
    """Non-last batch should have 'Layanan Lainnya' button pointing to next batch."""
    from modules.system_detection.sd_service import _build_related_service_batch_choices
    info = _build_related_service_batch_choices(
        related_services=["General"], language_code="id", batch_index=0, batch_size=5,
    )
    total = info["total_batches"]
    if total < 3:
        # not enough batches for this test
        return
    middle = _build_related_service_batch_choices(
        related_services=["General"], language_code="id", batch_index=1, batch_size=5,
    )
    has_more = any(
        (c.get("value") or "").startswith("RS_OTHER_BATCH_") for c in middle["choices"]
    )
    assert has_more, f"middle batch should have more-services button, got {middle['choices']!r}"


def test_batch_size_5_uniform():
    """All non-last batches should have exactly 5 actual services + 1 button."""
    from modules.system_detection.sd_service import _build_related_service_batch_choices
    info = _build_related_service_batch_choices(
        related_services=["General"], language_code="id", batch_index=0, batch_size=5,
    )
    total = info["total_batches"]
    for i in range(total - 1):  # all except last
        b = _build_related_service_batch_choices(
            related_services=["General"], language_code="id", batch_index=i, batch_size=5,
        )
        actual = [c for c in b["choices"] if not c["value"].startswith("RS_OTHER_BATCH_")]
        buttons = [c for c in b["choices"] if c["value"].startswith("RS_OTHER_BATCH_")]
        assert len(actual) == 5, f"batch {i} should have 5 actual services, got {len(actual)}"
        assert len(buttons) == 1, f"batch {i} should have 1 button, got {len(buttons)}"


def test_preferred_service_first_in_batch_0():
    """When related_services has a flow-backed service, it should appear FIRST."""
    from modules.system_detection.sd_service import _build_related_service_batch_choices
    result = _build_related_service_batch_choices(
        related_services=["WBS", "Mystery Shopping"],
        language_code="id",
        batch_index=0,
        batch_size=5,
    )
    choices = result["choices"]
    actual = [c for c in choices if not c["value"].startswith("RS_OTHER_BATCH_")]
    # First two should be WBS + Mystery Shopping
    first_value = actual[0]["value"]
    second_value = actual[1]["value"]
    assert "whistleblowing_system" in first_value, f"first should be WBS, got {first_value}"
    assert "mystery_shopping" in second_value, f"second should be MS, got {second_value}"


def test_total_batches_consistent_across_calls():
    """Calling batch 0, 1, ..., N should report consistent total_batches."""
    from modules.system_detection.sd_service import _build_related_service_batch_choices
    seen_totals = set()
    for i in range(5):
        info = _build_related_service_batch_choices(
            related_services=["General"], language_code="id", batch_index=i, batch_size=5,
        )
        seen_totals.add(info["total_batches"])
    assert len(seen_totals) == 1, f"total_batches should be stable, got {seen_totals}"


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
    print("\nAll tests passed.")
