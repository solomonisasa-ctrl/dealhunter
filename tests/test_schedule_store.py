from dealhunter.schedule_store import (
    DEFAULT_POLL_INTERVAL_MINUTES,
    load_poll_interval_minutes,
    save_poll_interval_minutes,
)


def test_load_missing_file_returns_default(tmp_path):
    path = tmp_path / "schedule.yaml"
    assert load_poll_interval_minutes(path) == DEFAULT_POLL_INTERVAL_MINUTES


def test_save_then_load_round_trips(tmp_path):
    path = tmp_path / "schedule.yaml"
    save_poll_interval_minutes(path, 30)
    assert load_poll_interval_minutes(path) == 30


def test_save_clamps_below_minimum(tmp_path):
    path = tmp_path / "schedule.yaml"
    saved = save_poll_interval_minutes(path, 0)
    assert saved == 1
    assert load_poll_interval_minutes(path) == 1


def test_save_clamps_negative(tmp_path):
    path = tmp_path / "schedule.yaml"
    save_poll_interval_minutes(path, -10)
    assert load_poll_interval_minutes(path) == 1


def test_load_clamps_hand_edited_invalid_value(tmp_path):
    path = tmp_path / "schedule.yaml"
    path.write_text("poll_interval_minutes: -5\n", encoding="utf-8")
    assert load_poll_interval_minutes(path) == 1


def test_header_comment_preserved(tmp_path):
    path = tmp_path / "schedule.yaml"
    save_poll_interval_minutes(path, 15)
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# How often Deal Hunter")
    assert "poll_interval_minutes: 15" in text
