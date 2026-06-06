from unittest import TestCase

from harness.comms.message import Message, Caste, Action


class FakeRouter:
    def __init__(self, responses: list[Message] | None = None):
        self.calls: list[Message] = []
        self.responses = responses or []

    def dispatch(self, msg: Message) -> Message:
        self.calls.append(msg)
        if self.responses:
            return self.responses.pop(0)
        return Message(
            caste=Caste.GAMMA,
            action=Action.INFER,
            payload={"result": "ok"},
        )


class ParseReviewTests(TestCase):
    def test_approved_verdict_tag(self):
        from harness.adev.engine import _parse_review
        r = _parse_review("VERDICT: APPROVED\nNo issues found.")
        self.assertEqual(r["verdict"], "APPROVED")

    def test_denied_verdict_tag(self):
        from harness.adev.engine import _parse_review
        r = _parse_review("VERDICT: DENIED\nISSUES:\n- bug (high)")
        self.assertEqual(r["verdict"], "DENIED")

    def test_approve_verdict_tag(self):
        from harness.adev.engine import _parse_review
        r = _parse_review("VERDICT: APPROVE\ngood enough")
        self.assertEqual(r["verdict"], "APPROVED")

    def test_approved_starts_with_text(self):
        from harness.adev.engine import _parse_review
        r = _parse_review("APPROVED - looks good")
        self.assertEqual(r["verdict"], "APPROVED")

    def test_preserves_feedback_text(self):
        from harness.adev.engine import _parse_review
        r = _parse_review("some feedback text")
        self.assertEqual(r["feedback"], "some feedback text")

    def test_reject_verdict_tag(self):
        from harness.adev.engine import _parse_review
        r = _parse_review("VERDICT: REJECT\nNot acceptable")
        self.assertEqual(r["verdict"], "REJECT")

    def test_continue_verdict_tag(self):
        from harness.adev.engine import _parse_review
        r = _parse_review("VERDICT: CONTINUE\nTry one more round")
        self.assertEqual(r["verdict"], "CONTINUE")


class ParseCasteTests(TestCase):
    def test_parse_alpha_by_name(self):
        from harness.adev.engine import _parse_caste
        self.assertEqual(_parse_caste("alpha"), Caste.ALPHA)

    def test_parse_gamma_by_letter(self):
        from harness.adev.engine import _parse_caste
        self.assertEqual(_parse_caste("g"), Caste.GAMMA)

    def test_parse_beta_by_symbol(self):
        from harness.adev.engine import _parse_caste
        self.assertEqual(_parse_caste("\u03b2"), Caste.BETA)

    def test_parse_unknown_raises(self):
        from harness.adev.engine import _parse_caste
        with self.assertRaises(ValueError):
            _parse_caste("delta")


class RoleConfigTests(TestCase):
    def test_default_roles_castes(self):
        from harness.adev.engine import DEFAULT_ROLES, Caste
        self.assertEqual(DEFAULT_ROLES["programmer"].caste, Caste.GAMMA)
        self.assertEqual(DEFAULT_ROLES["roaster"].caste, Caste.GAMMA)
        self.assertEqual(DEFAULT_ROLES["adjudicator"].caste, Caste.ALPHA)

    def test_resolve_roles_overrides_caste(self):
        from harness.adev.engine import AdversarialDevEngine, Caste
        roles = AdversarialDevEngine._resolve_roles({
            "programmer": {"caste": "alpha"},
            "adjudicator": {"caste": "gamma"},
        })
        self.assertEqual(roles["programmer"].caste, Caste.ALPHA)
        self.assertEqual(roles["roaster"].caste, Caste.GAMMA)
        self.assertEqual(roles["adjudicator"].caste, Caste.GAMMA)

    def test_resolve_roles_overrides_tokens(self):
        from harness.adev.engine import AdversarialDevEngine
        roles = AdversarialDevEngine._resolve_roles({
            "programmer": {"token_output": 4096},
        })
        self.assertEqual(roles["programmer"].token_output, 4096)


class AdversarialDevEngineTests(TestCase):
    def test_approved_first_round(self):
        from harness.adev.engine import AdversarialDevEngine
        router = FakeRouter([
            Message(caste=Caste.GAMMA, action=Action.INFER, payload={"result": "implemented X"}),
            Message(caste=Caste.GAMMA, action=Action.INFER, payload={"result": "VERDICT: APPROVED\nAll good."}),
        ])
        engine = AdversarialDevEngine(router=router)
        result = engine.run(task="add feature", max_rounds=3)
        self.assertEqual(result["status"], "approved")
        self.assertEqual(result["rounds"], 1)
        self.assertEqual(result["code_result"], "implemented X")

    def test_denied_then_approved(self):
        from harness.adev.engine import AdversarialDevEngine
        router = FakeRouter([
            Message(caste=Caste.GAMMA, action=Action.INFER, payload={"result": "v1 implementation"}),
            Message(caste=Caste.GAMMA, action=Action.INFER, payload={"result": "VERDICT: DENIED\nISSUES:\n- missing error handling (high)"}),
            Message(caste=Caste.GAMMA, action=Action.INFER, payload={"result": "v2 with error handling"}),
            Message(caste=Caste.GAMMA, action=Action.INFER, payload={"result": "VERDICT: APPROVED\nFixed."}),
        ])
        engine = AdversarialDevEngine(router=router)
        result = engine.run(task="add feature", max_rounds=3)
        self.assertEqual(result["status"], "approved")
        self.assertEqual(result["rounds"], 2)

    def test_adjudicator_called_after_max_rounds(self):
        from harness.adev.engine import AdversarialDevEngine
        router = FakeRouter([
            Message(caste=Caste.GAMMA, action=Action.INFER, payload={"result": "v1"}),
            Message(caste=Caste.GAMMA, action=Action.INFER, payload={"result": "VERDICT: DENIED\nISSUES:\n- bug (high)"}),
            Message(caste=Caste.GAMMA, action=Action.INFER, payload={"result": "v2"}),
            Message(caste=Caste.GAMMA, action=Action.INFER, payload={"result": "VERDICT: DENIED\nISSUES:\n- style (med)"}),
            Message(caste=Caste.GAMMA, action=Action.INFER, payload={"result": "v3"}),
            Message(caste=Caste.GAMMA, action=Action.INFER, payload={"result": "VERDICT: DENIED\nSTILL BROKEN"}),
            Message(caste=Caste.ALPHA, action=Action.INFER, payload={"result": "APPROVE - good enough"}),
        ])
        engine = AdversarialDevEngine(router=router)
        result = engine.run(task="add feature", max_rounds=3)
        self.assertEqual(result["rounds"], 3)
        self.assertIn("adjudication", result)
        self.assertEqual(len(router.calls), 7)

    def test_error_from_agent_raises(self):
        from harness.adev.engine import AdversarialDevEngine
        router = FakeRouter([
            Message(caste=Caste.GAMMA, action=Action.INFER, payload={"error": "server down"}),
        ])
        engine = AdversarialDevEngine(router=router)
        with self.assertRaises(RuntimeError) as ctx:
            engine.run(task="add feature", max_rounds=1)
        self.assertIn("server down", str(ctx.exception))

    def test_agent_calls_include_tools_when_enabled(self):
        from harness.adev.engine import AdversarialDevEngine
        router = FakeRouter([
            Message(caste=Caste.GAMMA, action=Action.INFER, payload={"result": "ok"}),
            Message(caste=Caste.GAMMA, action=Action.INFER, payload={"result": "VERDICT: APPROVED"}),
        ])
        engine = AdversarialDevEngine(router=router)
        engine.run(task="feature", max_rounds=1)

        programmer_call = router.calls[0]
        roaster_call = router.calls[1]
        self.assertTrue(programmer_call.payload.get("tools"), "programmer should have tools=True")
        self.assertTrue(roaster_call.payload.get("tools"), "roaster should have tools=True")

    def test_adjudicator_no_tools(self):
        from harness.adev.engine import AdversarialDevEngine
        router = FakeRouter([
            Message(caste=Caste.GAMMA, action=Action.INFER, payload={"result": "v1"}),
            Message(caste=Caste.GAMMA, action=Action.INFER, payload={"result": "VERDICT: DENIED\nISSUES:\n- bug (high)"}),
            Message(caste=Caste.GAMMA, action=Action.INFER, payload={"result": "v2"}),
            Message(caste=Caste.GAMMA, action=Action.INFER, payload={"result": "VERDICT: DENIED\nSTILL ISSUES"}),
            Message(caste=Caste.ALPHA, action=Action.INFER, payload={"result": "APPROVE"}),
        ])
        engine = AdversarialDevEngine(router=router)
        engine.run(task="feature", max_rounds=2)

        adjudicator_call = router.calls[4]
        self.assertNotIn("tools", adjudicator_call.payload)

    def test_uses_configured_caste_per_role(self):
        from harness.adev.engine import AdversarialDevEngine, Caste
        router = FakeRouter([
            Message(caste=Caste.ALPHA, action=Action.INFER, payload={"result": "alpha code"}),
            Message(caste=Caste.ALPHA, action=Action.INFER, payload={"result": "VERDICT: APPROVED"}),
        ])
        engine = AdversarialDevEngine(router=router, roles={
            "programmer": {"caste": "alpha"},
            "roaster": {"caste": "alpha"},
        })
        engine.run(task="feature", max_rounds=1)

        self.assertEqual(router.calls[0].caste, Caste.ALPHA)
        self.assertEqual(router.calls[1].caste, Caste.ALPHA)

    def test_run_overrides_default_roles(self):
        from harness.adev.engine import AdversarialDevEngine, Caste
        router = FakeRouter([
            Message(caste=Caste.ALPHA, action=Action.INFER, payload={"result": "alpha code"}),
            Message(caste=Caste.GAMMA, action=Action.INFER, payload={"result": "VERDICT: APPROVED"}),
        ])
        engine = AdversarialDevEngine(router=router)
        engine.run(task="feature", max_rounds=1, programmer={"caste": "alpha"})

        self.assertEqual(router.calls[0].caste, Caste.ALPHA)
        self.assertEqual(router.calls[1].caste, Caste.GAMMA)

    def test_delegate_called_when_provided(self):
        from harness.adev.engine import AdversarialDevEngine
        delegate_calls = []

        def fake_delegate(cfg, prompt):
            delegate_calls.append((cfg, prompt))
            return "delegated result"

        router = FakeRouter()
        engine = AdversarialDevEngine(router=router, delegate=fake_delegate)
        result = engine.run(task="feature", max_rounds=1,
                            roaster={"caste": "alpha"})

        self.assertGreaterEqual(len(delegate_calls), 1)
        self.assertEqual(result["code_result"], "delegated result")

    def test_delegate_returns_none_falls_back_to_router(self):
        from harness.adev.engine import AdversarialDevEngine

        def fake_delegate(cfg, prompt):
            return None

        router = FakeRouter([
            Message(caste=Caste.GAMMA, action=Action.INFER, payload={"result": "local result"}),
            Message(caste=Caste.GAMMA, action=Action.INFER, payload={"result": "VERDICT: APPROVED"}),
        ])
        engine = AdversarialDevEngine(router=router, delegate=fake_delegate)
        result = engine.run(task="feature", max_rounds=1)
        self.assertEqual(result["code_result"], "local result")
        self.assertEqual(len(router.calls), 2)

    def test_run_switches_to_workdir_and_restores_cwd(self):
        import os
        import tempfile
        from harness.adev.engine import AdversarialDevEngine

        seen_cwds: list[str] = []

        def fake_delegate(cfg, prompt):
            seen_cwds.append(os.getcwd())
            if "harsh but fair code reviewer" in prompt:
                return "VERDICT: APPROVED"
            return "implemented"

        original_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as d:
            engine = AdversarialDevEngine(router=FakeRouter(), delegate=fake_delegate)
            engine.run(task="feature", workdir=d, max_rounds=1)

        self.assertGreaterEqual(len(seen_cwds), 2)
        self.assertTrue(all(cwd == os.path.abspath(d) for cwd in seen_cwds))
        self.assertEqual(os.getcwd(), original_cwd)


class CLITests(TestCase):
    def test_adev_parser_added(self):
        from harness.cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["adev", "implement X"])
        self.assertEqual(args.command, "adev")
        self.assertEqual(args.task, "implement X")

    def test_adev_parser_defaults(self):
        from harness.cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["adev", "fix bug", "--rounds", "3"])
        self.assertEqual(args.rounds, 3)
        self.assertIsNone(args.workdir)

    def test_adev_parser_caste_flags(self):
        from harness.cli import build_parser
        parser = build_parser()
        args = parser.parse_args([
            "adev", "task",
            "--programmer-caste", "alpha",
            "--roaster-caste", "beta",
            "--adjudicator-caste", "gamma",
        ])
        self.assertEqual(args.programmer_caste, "alpha")
        self.assertEqual(args.roaster_caste, "beta")
        self.assertEqual(args.adjudicator_caste, "gamma")
