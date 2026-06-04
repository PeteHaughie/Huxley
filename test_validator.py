import unittest
from harness.selfmod.validator import validate_patch


class TestValidator(unittest.TestCase):
    def test_validator_ok(self):
        code = "def add(a,b):\n    return a+b\n"
        res = validate_patch("dummy.py", code)
        self.assertTrue(res["ok"])
        self.assertEqual(res["errors"], [])

    def test_validator_syntax_error(self):
        code = "def broken(:\n pass\n"
        res = validate_patch("x.py", code)
        self.assertFalse(res["ok"])
        self.assertTrue(any("syntax" in e for e in res["errors"]))
