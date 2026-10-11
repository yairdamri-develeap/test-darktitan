import contextlib
import io
import os
import subprocess
import sys
import unittest

import calculator

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calculator.py")


def run(*args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = calculator.main(list(args))
    return code, out.getvalue(), err.getvalue()


class OperatorTests(unittest.TestCase):
    def check(self, op, cases):
        for a, b, expected in cases:
            with self.subTest(a=a, op=op, b=b):
                code, out, _ = run(a, op, b)
                self.assertEqual(code, 0)
                self.assertAlmostEqual(float(out), expected)

    def test_add(self):
        self.check("+", [("3", "4", 7), ("-2", "9", 7), ("1.5", "2.25", 3.75), ("0.1", "0.2", 0.3)])

    def test_subtract(self):
        self.check("-", [("10", "4", 6), ("3", "8", -5), ("5.5", "2.25", 3.25), ("0.3", "0.1", 0.2)])

    def test_multiply(self):
        self.check("*", [("3", "4", 12), ("-2", "6", -12), ("1.5", "2", 3.0), ("0.5", "0.5", 0.25)])

    def test_divide(self):
        self.check("/", [("10", "2", 5), ("7", "2", 3.5), ("1.5", "0.5", 3.0), ("9.9", "3.3", 3.0)])


class OutputTests(unittest.TestCase):
    def test_int_result(self):
        self.assertEqual(run("3", "+", "4"), (0, "7\n", ""))

    def test_division_is_float(self):
        self.assertEqual(run("10", "/", "2"), (0, "5.0\n", ""))


class ErrorTests(unittest.TestCase):
    def assert_error(self, args):
        code, out, err = run(*args)
        self.assertNotEqual(code, 0)
        self.assertEqual(out, "")
        self.assertTrue(err)

    def test_divide_by_zero(self):
        self.assert_error(["5", "/", "0"])

    def test_non_numeric(self):
        self.assert_error(["abc", "+", "2"])
        self.assert_error(["nan", "+", "2"])

    def test_overflow(self):
        self.assert_error(["1" + "0" * 400, "/", "1"])

    def test_unknown_operator(self):
        self.assert_error(["1", "^", "2"])

    def test_wrong_arg_count(self):
        self.assert_error([])
        self.assert_error(["1", "+"])
        self.assert_error(["1", "+", "2", "3"])
        self.assertIn("Usage", run("1")[2])


class SubprocessTests(unittest.TestCase):
    def cli(self, *args):
        return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True)

    def test_cli(self):
        r = self.cli("3", "+", "4")
        self.assertEqual((r.returncode, r.stdout), (0, "7\n"))
        r = self.cli("5", "/", "0")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Error", r.stderr)


if __name__ == "__main__":
    unittest.main()
