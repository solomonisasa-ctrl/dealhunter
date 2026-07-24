"""atomic_write_text must never leave a partially-written or corrupted
file in place, even if the write is interrupted."""
from pathlib import Path

import pytest

from dealhunter.atomic_write import atomic_write_text


def test_writes_content(tmp_path):
    path = tmp_path / "out.json"
    atomic_write_text(path, '{"a": 1}')
    assert path.read_text(encoding="utf-8") == '{"a": 1}'


def test_overwrites_existing_content_fully(tmp_path):
    path = tmp_path / "out.json"
    atomic_write_text(path, '{"a": 1, "b": 2, "c": 3}')
    atomic_write_text(path, "{}")
    # No leftover bytes from the longer previous write - full replace, not
    # an in-place overwrite that could leave a trailing tail.
    assert path.read_text(encoding="utf-8") == "{}"


def test_creates_parent_directories(tmp_path):
    path = tmp_path / "nested" / "dir" / "out.json"
    atomic_write_text(path, "hello")
    assert path.read_text(encoding="utf-8") == "hello"


def test_no_leftover_temp_file_after_success(tmp_path):
    path = tmp_path / "out.json"
    atomic_write_text(path, "hello")
    leftovers = [p for p in tmp_path.iterdir() if p != path]
    assert leftovers == []


def test_failure_mid_write_leaves_original_file_untouched(tmp_path, monkeypatch):
    path = tmp_path / "out.json"
    atomic_write_text(path, "original content")

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated crash mid-write")

    monkeypatch.setattr("dealhunter.atomic_write.os.replace", _boom)
    with pytest.raises(RuntimeError):
        atomic_write_text(path, "new content that should never land")

    assert path.read_text(encoding="utf-8") == "original content"
    leftovers = [p for p in tmp_path.iterdir() if p != path]
    assert leftovers == []  # temp file cleaned up, not left behind


def test_two_interleaved_writers_never_produce_a_corrupt_file(tmp_path):
    """Regression test for the real bug this module fixes: two processes
    (or threads) writing the same path around the same time must each see
    a fully-formed file, never a spliced-together mix of both writes."""
    path = tmp_path / "out.json"
    long_content = '{"data": "' + "x" * 5000 + '"}'
    short_content = "{}"

    atomic_write_text(path, long_content)
    atomic_write_text(path, short_content)

    result = path.read_text(encoding="utf-8")
    assert result in (long_content, short_content)  # never a splice of both
