"""Unit tests for the in-memory progress tracker used by the dashboard's
'Refresh now' polling UI."""
from dealhunter import progress


def test_snapshot_before_start_is_not_running():
    progress.finish()  # reset any state left by another test
    snap = progress.snapshot()
    assert snap.get("running") is not True


def test_start_marks_running():
    progress.start()
    snap = progress.snapshot()
    assert snap["running"] is True
    assert snap["phase"] == "starting"


def test_update_after_start_sets_fields():
    progress.start()
    progress.update(phase="analyzing", detail="item-a (ebay) - listing 2/5", current=1.2, total=3)
    snap = progress.snapshot()
    assert snap["phase"] == "analyzing"
    assert snap["detail"] == "item-a (ebay) - listing 2/5"
    assert snap["current"] == 1.2
    assert snap["total"] == 3


def test_update_before_start_is_a_noop():
    progress.finish()
    progress.update(phase="analyzing", current=5, total=10)
    snap = progress.snapshot()
    assert snap.get("running") is not True
    assert snap.get("phase") != "analyzing"


def test_finish_marks_not_running_and_clears_error_by_default():
    progress.start()
    progress.finish()
    snap = progress.snapshot()
    assert snap["running"] is False
    assert snap["error"] is None


def test_finish_with_error_records_it():
    progress.start()
    progress.finish(error="boom")
    snap = progress.snapshot()
    assert snap["running"] is False
    assert snap["error"] == "boom"


def test_total_is_never_zero_to_avoid_division_by_zero():
    progress.start()
    progress.update(phase="fetching", current=0, total=0)
    snap = progress.snapshot()
    assert snap["total"] >= 1
