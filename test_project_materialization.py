import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harness.board import JobBoard, Level, Task
from harness.projects.manager import (
    archive_epic,
    get_project,
    materialize_project,
    write_compiled_suggestions,
)


class ProjectMaterializationTests(unittest.TestCase):
    def test_write_compiled_suggestions_splits_multiple_options(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            proj_dir = Path(tmpdir) / "20260518T080000-demo"
            proj_dir.mkdir(parents=True, exist_ok=True)

            manifest = write_compiled_suggestions(
                proj_dir,
                """--- OPTION: Fast API
--- FILE: README.md
# Fast API
---
--- FILE: src/app.py
print("fast")
--- END OPTION
--- OPTION: CLI Tool
--- FILE: README.md
# CLI Tool
---
--- FILE: cli/main.py
print("cli")
--- END OPTION
""",
            )

            self.assertEqual(len(manifest), 2)
            self.assertEqual(manifest[0]["folder"], "01-fast-api")
            self.assertEqual(manifest[1]["folder"], "02-cli-tool")
            self.assertTrue((proj_dir / "suggestions" / "01-fast-api" / "src" / "app.py").exists())
            self.assertTrue((proj_dir / "suggestions" / "02-cli-tool" / "cli" / "main.py").exists())

    def test_materialize_project_copies_each_suggestion_to_its_own_folder(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            board_dir = temp_root / "board"
            projects_dir = temp_root / "projects"
            board_dir.mkdir(parents=True, exist_ok=True)
            projects_dir.mkdir(parents=True, exist_ok=True)

            with patch("harness.board.core.HUXLEY_BOARD_DIR", board_dir), patch("harness.projects.manager.HUXLEY_PROJECTS_DIR", projects_dir):
                board = JobBoard()
                epic = Task(level=Level.EPIC, title="Ship demo", prompt="Build a demo app")
                board.create(epic)
                epic.transition(board.get(epic.id).state.READY)
                board.update(epic)
                epic = board.claim(Level.EPIC, caste_tag="α")
                self.assertIsNotNone(epic)
                board.complete(epic.id, "Research summary")
                done_epic = board.get(epic.id)
                proj_dir = archive_epic(done_epic, board)
                write_compiled_suggestions(
                    proj_dir,
                    """--- OPTION: web
--- FILE: README.md
web
--- END OPTION
--- OPTION: desktop
--- FILE: README.md
desktop
--- FILE: app/main.ts
console.log("desktop")
--- END OPTION
""",
                )

                result = materialize_project(proj_dir.name, destination=temp_root / "repo")
                project_view = get_project(proj_dir.name)

            self.assertIsNotNone(result)
            self.assertEqual(len(result["suggestions"]), 2)
            self.assertTrue((temp_root / "repo" / "01-web" / "README.md").exists())
            self.assertTrue((temp_root / "repo" / "02-desktop" / "app" / "main.ts").exists())
            manifest = json.loads((temp_root / "repo" / "materialized.json").read_text())
            self.assertEqual(len(manifest["suggestions"]), 2)
            self.assertEqual(len(project_view["suggestions"]), 2)


if __name__ == "__main__":
    unittest.main()
