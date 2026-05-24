import json
import os
import sys
import tempfile
import subprocess
import unittest


REPO_ROOT = os.path.dirname(os.path.abspath(__file__))


def _run_cli(home_dir: str, *args: str, stdin: str = "", expect_fail: bool = False) -> tuple:
    env = {**os.environ, "HOME": home_dir, "USERPROFILE": home_dir, "HOMEPATH": home_dir, "PYTHONPATH": REPO_ROOT}
    result = subprocess.run(
        [sys.executable, "-m", "harness.cli", *args],
        capture_output=True, text=True,
        input=stdin,
        env=env,
        cwd=REPO_ROOT,
    )
    if not expect_fail:
        if result.returncode != 0:
            raise AssertionError(f"CLI failed: rc={result.returncode} stderr={result.stderr!r}")
    return result.stdout, result.stderr, result.returncode


class TestPatchCLI(unittest.TestCase):
    def test_patch_list_and_rollback(self):
        with tempfile.TemporaryDirectory() as td:
            home = td
            patches = os.path.join(home, ".huxley", "patches")
            os.makedirs(patches, exist_ok=True)
            pid = "abc123def456"
            fname = "test_target.py"
            bak_path = os.path.join(patches, f"{pid}_{fname}.bak")
            target_dir = os.path.join(home, ".huxley", "somepath")
            os.makedirs(target_dir, exist_ok=True)
            target_path = os.path.join(target_dir, fname)
            meta_path = os.path.join(patches, f"{pid}.meta")
            with open(meta_path, "w") as f:
                f.write(json.dumps({"original_path": target_path}))
            with open(bak_path, "w") as f:
                f.write("# backup content\n")
            with open(target_path, "w") as f:
                f.write("# original content\n")

            out, _, _ = _run_cli(home, "patch", "--list")
            self.assertIn(f"γ|patch|entry|{pid}|test_target.py", out)

            out, _, _ = _run_cli(home, "patch", "--rollback", pid)
            self.assertIn(f"γ|patch|rollback|ok|{pid}", out)
            with open(target_path) as f:
                data = f.read()
            self.assertIn("# backup content", data)

    def test_patch_list_empty(self):
        with tempfile.TemporaryDirectory() as td:
            out, _, _ = _run_cli(td, "patch", "--list")
            self.assertIn("γ|patch|list|empty", out)

    def test_patch_rejects_ambiguous_list_flags(self):
        with tempfile.TemporaryDirectory() as td:
            out, _, rc = _run_cli(td, "patch", "--list", "--review", "dummy.py", expect_fail=True)
            self.assertNotEqual(rc, 0)
            self.assertIn("--list/--rollback cannot be combined", out)

    def test_patch_rollback_rejects_meta_path_outside_allowed_roots(self):
        with tempfile.TemporaryDirectory() as td:
            home = td
            patches = os.path.join(home, ".huxley", "patches")
            os.makedirs(patches, exist_ok=True)
            pid = "blockedmeta01"
            outside_path = os.path.join(home, "outside.py")
            with open(outside_path, "w") as f:
                f.write("# outside target\n")
            with open(os.path.join(patches, f"{pid}.meta"), "w") as f:
                f.write(json.dumps({"original_path": outside_path}))
            with open(os.path.join(patches, f"{pid}_outside.py.bak"), "w") as f:
                f.write("# backup content\n")

            out, _, rc = _run_cli(home, "patch", "--rollback", pid, expect_fail=True)
            self.assertNotEqual(rc, 0)
            self.assertIn(f"γ|patch|rollback|not_found|{pid}", out)
            with open(outside_path) as f:
                self.assertEqual("# outside target\n", f.read())

    def test_patch_rollback_legacy_symlink_must_resolve_inside_allowed_roots(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks unsupported on this platform")
        with tempfile.TemporaryDirectory() as td:
            home = td
            patches = os.path.join(home, ".huxley", "patches")
            target_dir = os.path.join(home, ".huxley", "somepath")
            os.makedirs(patches, exist_ok=True)
            os.makedirs(target_dir, exist_ok=True)
            pid = "legacysymlink"
            fname = "test_target.py"
            bak_path = os.path.join(patches, f"{pid}_{fname}.bak")
            outside_path = os.path.join(home, "outside.py")
            with open(outside_path, "w") as f:
                f.write("# outside target\n")
            with open(bak_path, "w") as f:
                f.write("# backup content\n")
            try:
                os.symlink(outside_path, os.path.join(target_dir, fname))
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"symlinks unavailable on this platform: {exc}")

            out, _, rc = _run_cli(home, "patch", "--rollback", pid, expect_fail=True)
            self.assertNotEqual(rc, 0)
            self.assertIn(f"γ|patch|rollback|not_found|{pid}", out)
            with open(outside_path) as f:
                self.assertEqual("# outside target\n", f.read())
            self.assertTrue(os.path.exists(bak_path))

    def test_patch_rollback_rejects_malformed_meta(self):
        with tempfile.TemporaryDirectory() as td:
            home = td
            patches = os.path.join(home, ".huxley", "patches")
            os.makedirs(patches, exist_ok=True)
            pid = "badmeta123456"
            with open(os.path.join(patches, f"{pid}.meta"), "w") as f:
                f.write(json.dumps(["not-a-dict"]))
            with open(os.path.join(patches, f"{pid}_dummy.py.bak"), "w") as f:
                f.write("# backup content\n")

            out, _, rc = _run_cli(home, "patch", "--rollback", pid, expect_fail=True)
            self.assertNotEqual(rc, 0)
            self.assertIn(f"γ|patch|rollback|not_found|{pid}", out)

    def test_patch_rollback_legacy_ignores_directory_matches(self):
        with tempfile.TemporaryDirectory() as td:
            home = td
            patches = os.path.join(home, ".huxley", "patches")
            os.makedirs(patches, exist_ok=True)
            pid = "legacyfile123"
            fname = "test_target.py"
            bak_path = os.path.join(patches, f"{pid}_{fname}.bak")
            target_dir = os.path.join(home, ".huxley", "somepath")
            target_path = os.path.join(target_dir, fname)
            os.makedirs(target_path, exist_ok=True)
            actual_file_dir = os.path.join(home, ".huxley", "actual")
            os.makedirs(actual_file_dir, exist_ok=True)
            actual_file_path = os.path.join(actual_file_dir, fname)
            with open(actual_file_path, "w") as f:
                f.write("# original content\n")
            with open(bak_path, "w") as f:
                f.write("# backup content\n")

            out, _, _ = _run_cli(home, "patch", "--rollback", pid)
            self.assertIn(f"γ|patch|rollback|ok|{pid}", out)
            with open(actual_file_path) as f:
                self.assertEqual("# backup content\n", f.read())

    def test_patch_requires_file_for_normal_flow(self):
        with tempfile.TemporaryDirectory() as td:
            out, _, rc = _run_cli(td, "patch", expect_fail=True)
            self.assertNotEqual(rc, 0)
            self.assertIn("file argument required", out)

    def test_patch_review_posts_board(self):
        with tempfile.TemporaryDirectory() as td:
            home = td
            os.makedirs(os.path.join(home, ".huxley"), exist_ok=True)
            fpath = os.path.join(home, ".huxley", "dummy.py")
            with open(fpath, "w") as f:
                f.write("print(1)\n")

            out, _, _ = _run_cli(home, "patch", "--review", fpath, stdin="print(2)\n")
            self.assertIn("γ|patch|ok", out)
            self.assertIn("γ|patch|posted", out)

            board_dir = os.path.join(home, ".huxley", "board")
            files = []
            if os.path.exists(board_dir):
                files = [n for n in os.listdir(board_dir) if n.endswith('.json')]
            self.assertTrue(files, "board task not created")


if __name__ == "__main__":
    unittest.main()
