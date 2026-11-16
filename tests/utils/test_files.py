import os
import stat

import pytest

from larklab.utils import files
from larklab.utils.files import read_json_or, write_text_atomically


def test_writes_new_files_readable_by_the_owner_and_group(tmp_path):
    target = tmp_path / "out.json"

    write_text_atomically(target, "hello")

    assert target.read_text() == "hello"
    assert stat.S_IMODE(target.stat().st_mode) == 0o644


def test_replacing_a_file_keeps_its_permissions(tmp_path):
    target = tmp_path / "out.json"
    target.write_text("old")
    target.chmod(0o640)

    write_text_atomically(target, "new")

    assert target.read_text() == "new"
    assert stat.S_IMODE(target.stat().st_mode) == 0o640


def test_a_failed_replace_leaves_the_original_and_no_temp_file(tmp_path, monkeypatch):
    target = tmp_path / "out.json"
    target.write_text("original")

    def explode(source, destination):
        raise OSError("disk went away")

    monkeypatch.setattr(files.os, "replace", explode)

    with pytest.raises(OSError, match="disk went away"):
        write_text_atomically(target, "half written")

    assert target.read_text() == "original"
    assert os.listdir(tmp_path) == ["out.json"]  # the temp file was cleaned up


def test_a_missing_json_file_gives_the_default_quietly(tmp_path, caplog):
    assert read_json_or(tmp_path / "none.json", len, default=-1, what="x") == -1
    assert caplog.text == ""


def test_a_damaged_json_file_gives_the_default_and_a_warning(tmp_path, caplog):
    path = tmp_path / "bad.json"
    path.write_text("{ not json")

    assert read_json_or(path, len, default=-1, what="demo") == -1
    assert "Ignoring unreadable demo file" in caplog.text


def test_json_of_the_wrong_shape_gives_the_default(tmp_path):
    path = tmp_path / "shape.json"
    path.write_text("[1, 2]")

    assert read_json_or(path, lambda raw: raw["key"], default="d", what="x") == "d"
    assert read_json_or(path, lambda raw: sum(raw), default=0, what="x") == 3
