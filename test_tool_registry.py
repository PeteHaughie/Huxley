from pathlib import Path

from harness.tool.registry import ToolRegistry
from harness.tool.decorator import tool, clear_registered_tools


def teardown_function():
    clear_registered_tools()


def test_registry_has_builtins():
    reg = ToolRegistry()
    names = reg.list_tools()
    assert "read_file" in names
    assert "write_file" in names
    assert "edit_file" in names
    assert "glob_files" in names
    assert "grep" in names

def test_shell_tools_require_opt_in():
    reg = ToolRegistry()
    assert "bash" not in reg.list_tools()
    reg = ToolRegistry(builtins_cfg={"shell": True})
    assert "bash" in reg.list_tools()


def test_shell_disable_does_not_mutate_other_registry_instances():
    reg_enabled = ToolRegistry(builtins_cfg={"shell": True})
    assert reg_enabled.has_tool("bash")
    reg_disabled = ToolRegistry(builtins_cfg={"shell": False})
    assert not reg_disabled.has_tool("bash")
    assert reg_enabled.has_tool("bash")


def test_registry_definitions_are_openai_compatible():
    reg = ToolRegistry()
    defs = reg.definitions()
    assert len(defs) > 5
    for d in defs:
        assert d["type"] == "function"
        assert "name" in d["function"]
        assert "description" in d["function"]
        assert "parameters" in d["function"]


def test_get_handler():
    reg = ToolRegistry()
    handler = reg.get_handler("read_file")
    assert handler is not None
    assert callable(handler)


def test_get_handler_unknown():
    reg = ToolRegistry()
    assert reg.get_handler("nonexistent_tool") is None


def test_has_tool():
    reg = ToolRegistry()
    assert reg.has_tool("read_file")
    assert not reg.has_tool("unicorn_rainbow")


def test_scan_skills_does_not_crash():
    reg = ToolRegistry(builtins_cfg={"skills": True})
    reg.scan_skills()


def test_reset():
    @tool()
    def my_tool():
        pass

    reg = ToolRegistry()
    assert reg.has_tool("my_tool")
    ToolRegistry.reset()
    clear_registered_tools()
    reg2 = ToolRegistry()
    assert not reg2.has_tool("my_tool")


def test_scan_skills_loads_tools(tmp_path: Path):
    skills_dir = tmp_path / ".agents" / "skills" / "testskill"
    tools_dir = skills_dir / "tools"
    tools_dir.mkdir(parents=True)

    tool_code = """
from harness.tool.decorator import tool

@tool(description=\"A test tool from a skill\")
def skill_tool(name: str) -> str:
    return f\"hello {name}\"
"""
    (tools_dir / "greeter.py").write_text(tool_code)

    import harness.tool.registry as reg_mod
    original_dirs = reg_mod._skill_dirs

    try:
        reg_mod._skill_dirs = lambda: [skills_dir.parent]
        reg = ToolRegistry(builtins_cfg={"skills": True})
        reg.scan_skills()
        assert reg.has_tool("skill_tool"), f"tools: {reg.list_tools()}"
        handler = reg.get_handler("skill_tool")
        assert handler("world") == "hello world"
    finally:
        reg_mod._skill_dirs = original_dirs


def test_scan_skills_uses_unique_module_names_per_skills_root(tmp_path: Path):
    agents_skill = tmp_path / ".agents" / "skills" / "common" / "tools"
    huxley_skill = tmp_path / ".huxley" / "skills" / "common" / "tools"
    agents_skill.mkdir(parents=True)
    huxley_skill.mkdir(parents=True)

    (agents_skill / "toolbox.py").write_text(
        """
from harness.tool.decorator import tool

@tool()
def from_agents() -> str:
    return "agents"
"""
    )
    (huxley_skill / "toolbox.py").write_text(
        """
from harness.tool.decorator import tool

@tool()
def from_huxley() -> str:
    return "huxley"
"""
    )

    import harness.tool.registry as reg_mod

    original_dirs = reg_mod._skill_dirs
    try:
        reg_mod._skill_dirs = lambda: [tmp_path / ".agents" / "skills", tmp_path / ".huxley" / "skills"]
        reg = ToolRegistry(builtins_cfg={"skills": True})
        reg.scan_skills()
        assert reg.has_tool("from_agents")
        assert reg.has_tool("from_huxley")
    finally:
        reg_mod._skill_dirs = original_dirs


def test_skills_disabled_hides_previously_scanned_skill_tools(tmp_path: Path):
    skills_dir = tmp_path / ".agents" / "skills" / "testskill"
    tools_dir = skills_dir / "tools"
    tools_dir.mkdir(parents=True)

    (tools_dir / "greeter.py").write_text(
        """
from harness.tool.decorator import tool

@tool(description="A test tool from a skill")
def skill_tool(name: str) -> str:
    return f"hello {name}"
"""
    )

    import harness.tool.registry as reg_mod

    original_dirs = reg_mod._skill_dirs
    try:
        reg_mod._skill_dirs = lambda: [skills_dir.parent]
        enabled = ToolRegistry(builtins_cfg={"skills": True})
        enabled.scan_skills()
        assert enabled.has_tool("skill_tool")

        disabled = ToolRegistry(builtins_cfg={"skills": False})
        assert not disabled.has_tool("skill_tool")
        assert "skill_tool" not in disabled.list_tools()
        assert disabled.get_handler("skill_tool") is None
    finally:
        reg_mod._skill_dirs = original_dirs


import tempfile
import unittest
from inspect import signature


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
