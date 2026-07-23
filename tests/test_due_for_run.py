import time

from dealhunter.models import HealthReport
from dealhunter.pipeline import due_for_run, is_paused
from dealhunter.schedule_store import save_paused, save_poll_interval_minutes
from dealhunter.storage import health_store


class _FakeSettings:
    """Minimal duck-typed stand-in for config.settings.Settings - due_for_run
    only ever touches these two paths."""

    def __init__(self, tmp_path):
        self.schedule_path = tmp_path / "schedule.yaml"
        self.health_path = tmp_path / "health.json"


def test_due_for_run_true_when_no_history(tmp_path):
    settings = _FakeSettings(tmp_path)
    save_poll_interval_minutes(settings.schedule_path, 30)
    assert due_for_run(settings) is True


def test_due_for_run_false_right_after_a_run(tmp_path):
    settings = _FakeSettings(tmp_path)
    save_poll_interval_minutes(settings.schedule_path, 30)
    health_store.append_health(settings.health_path, HealthReport(timestamp=time.time()))
    assert due_for_run(settings) is False


def test_due_for_run_true_once_interval_elapsed(tmp_path):
    settings = _FakeSettings(tmp_path)
    save_poll_interval_minutes(settings.schedule_path, 30)
    old_timestamp = time.time() - 31 * 60
    health_store.append_health(settings.health_path, HealthReport(timestamp=old_timestamp))
    assert due_for_run(settings) is True


def test_due_for_run_respects_shorter_interval(tmp_path):
    settings = _FakeSettings(tmp_path)
    save_poll_interval_minutes(settings.schedule_path, 5)
    just_under = time.time() - 4 * 60
    health_store.append_health(settings.health_path, HealthReport(timestamp=just_under))
    assert due_for_run(settings) is False

    just_over = time.time() - 6 * 60
    health_store.append_health(settings.health_path, HealthReport(timestamp=just_over))
    assert due_for_run(settings) is True


def test_is_paused_defaults_false(tmp_path):
    settings = _FakeSettings(tmp_path)
    assert is_paused(settings) is False


def test_is_paused_true_after_pausing(tmp_path):
    settings = _FakeSettings(tmp_path)
    save_paused(settings.schedule_path, True)
    assert is_paused(settings) is True


def test_is_paused_false_after_resuming(tmp_path):
    settings = _FakeSettings(tmp_path)
    save_paused(settings.schedule_path, True)
    save_paused(settings.schedule_path, False)
    assert is_paused(settings) is False


def test_pause_and_interval_coexist_in_same_file(tmp_path):
    settings = _FakeSettings(tmp_path)
    save_poll_interval_minutes(settings.schedule_path, 20)
    save_paused(settings.schedule_path, True)
    # Setting one shouldn't clobber the other in the same YAML file.
    from dealhunter.schedule_store import load_poll_interval_minutes

    assert load_poll_interval_minutes(settings.schedule_path) == 20
    assert is_paused(settings) is True
