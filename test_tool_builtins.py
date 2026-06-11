import tempfile
import unittest
from inspect import signature
from pathlib import Path
from unittest.mock import patch

from harness.tool.builtins import filesystem, search, shell, tools
from harness.tool.decorator import clear_registered_tools


def teardown_function():
    clear_registered_tools()


# -- filesystem tests --


def test_read_file(tmp_path: Path):
    filesystem.allow_path(str(tmp_path))
    f = tmp_path / "test.txt"
    f.write_text("hello world")
    result = filesystem.read_file(str(f))
    assert "hello world" in result
    assert "[read 1/1 lines" in result


def test_read_file_with_offset(tmp_path: Path):
    filesystem.allow_path(str(tmp_path))
    f = tmp_path / "test.txt"
    f.write_text("line1\nline2\nline3\n")
    result = filesystem.read_file(str(f), offset=1)
    assert "line2" in result
    assert "line1" not in result


def test_read_file_with_limit(tmp_path: Path):
    filesystem.allow_path(str(tmp_path))
    f = tmp_path / "test.txt"
    f.write_text("line1\nline2\nline3\n")
    result = filesystem.read_file(str(f), limit=2)
    assert "line1" in result
    assert "line3" not in result


def test_read_file_not_found():
    result = filesystem.read_file("/nonexistent/path/file.txt")
    assert "Error: path not allowed" in result


def test_write_file(tmp_path: Path):
    filesystem.allow_path(str(tmp_path))
    f = tmp_path / "output.txt"
    result = filesystem.write_file(str(f), "new content")
    assert "Wrote" in result
    assert f.read_text() == "new content"


def test_write_file_creates_dirs(tmp_path: Path):
    filesystem.allow_path(str(tmp_path))
    f = tmp_path / "a" / "b" / "c.txt"
    result = filesystem.write_file(str(f), "deep")
    assert "Wrote" in result
    assert f.read_text() == "deep"


def test_edit_file(tmp_path: Path):
    filesystem.allow_path(str(tmp_path))
    f = tmp_path / "edit.txt"
    f.write_text("hello world foo")
    result = filesystem.edit_file(str(f), "world", "there")
    assert "Edited" in result
    assert f.read_text() == "hello there foo"


def test_edit_file_not_found():
    result = filesystem.edit_file("/nonexistent/file.txt", "a", "b")
    assert "Error: path not allowed" in result


def test_edit_string_not_found(tmp_path: Path):
    filesystem.allow_path(str(tmp_path))
    f = tmp_path / "edit.txt"
    f.write_text("hello")
    result = filesystem.edit_file(str(f), "world", "there")
    assert "Error: old_string not found" in result


def test_delete_file(tmp_path: Path):
    filesystem.allow_path(str(tmp_path))
    f = tmp_path / "delete_me.txt"
    f.write_text("bye")
    result = filesystem.delete_file(str(f))
    assert "Deleted" in result
    assert not f.exists()


def test_delete_file_not_found():
    result = filesystem.delete_file("/nonexistent/file.txt")
    assert "Error: path not allowed" in result


def test_glob_files(tmp_path: Path):
    filesystem.allow_path(str(tmp_path))
    (tmp_path / "a.py").write_text("")
    (tmp_path / "b.py").write_text("")
    (tmp_path / "c.txt").write_text("")
    result = filesystem.glob_files("*.py", path=str(tmp_path))
    assert "2 matches" in result
    assert "a.py" in result
    assert "b.py" in result
    assert "c.txt" not in result


def test_create_directory(tmp_path: Path):
    filesystem.allow_path(str(tmp_path))
    d = tmp_path / "newdir"
    result = filesystem.create_directory(str(d))
    assert "Created" in result
    assert d.is_dir()


def test_list_directory(tmp_path: Path):
    filesystem.allow_path(str(tmp_path))
    (tmp_path / "a.txt").write_text("")
    (tmp_path / "sub").mkdir()
    result = filesystem.list_directory(str(tmp_path))
    assert "a.txt" in result
    assert "sub/" in result


def test_list_directory_empty(tmp_path: Path):
    filesystem.allow_path(str(tmp_path))
    empty = tmp_path / "empty"
    empty.mkdir()
    result = filesystem.list_directory(str(empty))
    assert "empty" in result


# -- path restriction tests --


def test_read_file_disallowed_path():
    result = filesystem.read_file("/etc/passwd")
    assert "Error: path not allowed" in result


def test_write_file_disallowed_path():
    result = filesystem.write_file("/etc/evil.txt", "pwned")
    assert "Error: path not allowed" in result


def test_edit_file_disallowed_path():
    result = filesystem.edit_file("/etc/passwd", "root", "admin")
    assert "Error: path not allowed" in result


def test_delete_file_disallowed_path():
    result = filesystem.delete_file("/etc/shadow")
    assert "Error: path not allowed" in result


def test_filesystem_allow_path_initializes_roots_before_append(tmp_path: Path):
    original_roots = list(filesystem._PROJECT_ROOTS)
    original_init_done = filesystem._INIT_PROJECT_ROOTS_DONE
    filesystem._PROJECT_ROOTS.clear()
    filesystem._INIT_PROJECT_ROOTS_DONE = False
    try:
        cwd_at_allow = tmp_path / "cwd_at_allow"
        cwd_after = tmp_path / "cwd_after"
        allowed = tmp_path / "allowed"
        cwd_at_allow.mkdir()
        cwd_after.mkdir()
        allowed.mkdir()

        with patch("harness.tool.builtins.filesystem.Path.cwd", return_value=cwd_at_allow):
            filesystem.allow_path(str(allowed))
        with patch("harness.tool.builtins.filesystem.Path.cwd", return_value=cwd_after):
            result = filesystem.read_file(str(cwd_after / "outside.txt"))
        assert "Error: path not allowed" in result
    finally:
        filesystem._PROJECT_ROOTS.clear()
        filesystem._PROJECT_ROOTS.extend(original_roots)
        filesystem._INIT_PROJECT_ROOTS_DONE = original_init_done


# -- search tests --


def test_grep(tmp_path: Path):
    search.allow_path(str(tmp_path))
    f = tmp_path / "test.py"
    f.write_text("def foo():\n    pass\ndef bar():\n    pass\n")
    result = search.grep("def ", path=str(tmp_path))
    assert "2 matches" in result


def test_grep_no_matches(tmp_path: Path):
    search.allow_path(str(tmp_path))
    f = tmp_path / "test.py"
    f.write_text("nothing here")
    result = search.grep("xyzzy", path=str(tmp_path))
    assert "No matches" in result


def test_grep_fallback_skips_hidden_dirs(tmp_path: Path):
    search.allow_path(str(tmp_path))
    visible = tmp_path / "visible.py"
    visible.write_text("needle")
    hidden_dir = tmp_path / ".hidden"
    hidden_dir.mkdir()
    (hidden_dir / "secret.py").write_text("needle")
    with patch("subprocess.run", side_effect=FileNotFoundError()):
        result = search.grep("needle", path=str(tmp_path))
    assert "visible.py" in result
    assert ".hidden/secret.py" not in result


def test_grep_fallback_does_not_skip_visible_top_level_files(tmp_path: Path):
    search.allow_path(str(tmp_path))
    visible = tmp_path / "visible.py"
    visible.write_text("needle")
    with patch("subprocess.run", side_effect=FileNotFoundError()):
        result = search.grep("needle", path=str(tmp_path))
    assert "visible.py" in result


# -- shell tests --


def test_bash_echo(tmp_path: Path):
    shell.allow_path(str(tmp_path))
    result = shell.bash("echo hello", workdir=str(tmp_path))
    assert "hello" in result


def test_bash_exit_code(tmp_path: Path):
    shell.allow_path(str(tmp_path))
    result = shell.bash("false", workdir=str(tmp_path))
    assert "exit code 1" in result


def test_bash_timeout(tmp_path: Path):
    shell.allow_path(str(tmp_path))
    result = shell.bash("sleep 10", workdir=str(tmp_path), timeout=1)
    assert "timed out" in result


def test_bash_disallowed_workdir():
    result = shell.bash("echo test", workdir="/etc")
    assert "Error: working directory not allowed" in result


def test_tool_info_accepts_builtin_prefix():
    clear_registered_tools()
    reg = __import__("harness.tool.registry", fromlist=["ToolRegistry"]).ToolRegistry()
    tools.set_registry(reg)

    result = tools.tool_info("builtin:read_file")

    assert '"name": "read_file"' in result


def _run_test(fn):
    try:
        if "tmp_path" in signature(fn).parameters:
            with tempfile.TemporaryDirectory() as d:
                fn(Path(d))
        else:
            fn()
    finally:
        teardown_function()


def load_tests(loader, tests, pattern):  # pragma: no cover
    suite = unittest.TestSuite()
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            suite.addTest(unittest.FunctionTestCase(lambda fn=fn: _run_test(fn), description=name))
    return suite
