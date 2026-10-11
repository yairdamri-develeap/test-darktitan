import json
import re
import shutil
import subprocess
import threading
import unittest
import urllib.error
import urllib.request
from http.server import HTTPServer

import calculator_web


class ServerTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), calculator_web.CalculatorHandler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, path, body=None, method=None):
        data = body.encode() if isinstance(body, str) else body
        req = urllib.request.Request(self.base + path, data=data, method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as err:
            with err:
                return err.code, err.read()

    def calculate(self, payload):
        body = payload if isinstance(payload, str) else json.dumps(payload)
        status, raw = self.request("/calculate", body, "POST")
        return status, json.loads(raw)


class CalculateTests(ServerTestCase):
    def test_add(self):
        self.assertEqual(self.calculate({"left": "3", "op": "+", "right": "4"}), (200, {"result": 7}))

    def test_all_operators(self):
        cases = [("-", "9", "4", 5), ("*", "6", "7", 42), ("/", "9", "4", 2.25), ("+", "1.5", "2.25", 3.75)]
        for op, left, right, expected in cases:
            with self.subTest(op=op):
                status, body = self.calculate({"left": left, "op": op, "right": right})
                self.assertEqual(status, 200)
                self.assertAlmostEqual(body["result"], expected)

    def test_numeric_json_operands(self):
        self.assertEqual(self.calculate({"left": 3, "op": "+", "right": 4.5}), (200, {"result": 7.5}))

    def test_division_by_zero(self):
        status, body = self.calculate({"left": "5", "op": "/", "right": "0"})
        self.assertEqual(status, 400)
        self.assertIn("division by zero", body["error"])

    def test_invalid_number_names_operand(self):
        status, body = self.calculate({"left": "abc", "op": "+", "right": "2"})
        self.assertEqual(status, 400)
        self.assertIn("abc", body["error"])

    def test_invalid_right_operand(self):
        status, body = self.calculate({"left": "1", "op": "+", "right": "nan"})
        self.assertEqual(status, 400)
        self.assertIn("nan", body["error"])

    def test_bad_operand_types(self):
        for bad in (None, True, [1], {"a": 1}):
            with self.subTest(bad=bad):
                status, body = self.calculate({"left": bad, "op": "+", "right": "1"})
                self.assertEqual(status, 400)
                self.assertIn("error", body)

    def test_unknown_operator(self):
        for op in ("^", "", 5, None):
            with self.subTest(op=op):
                status, body = self.calculate({"left": "1", "op": op, "right": "1"})
                self.assertEqual(status, 400)
                self.assertIn("error", body)

    def test_missing_field(self):
        status, body = self.calculate({"left": "1", "op": "+"})
        self.assertEqual(status, 400)
        self.assertIn("right", body["error"])

    def test_invalid_json(self):
        for raw in ("nope", "", "[1, 2]", '"3+4"'):
            with self.subTest(raw=raw):
                status, body = self.calculate(raw)
                self.assertEqual(status, 400)
                self.assertIn("error", body)

    def test_overflow(self):
        for payload in (
            {"left": "1e308", "op": "*", "right": "10"},
            {"left": "1" + "0" * 400, "op": "/", "right": "1"},
        ):
            with self.subTest(payload=payload):
                status, body = self.calculate(payload)
                self.assertEqual(status, 400)
                self.assertIn("too large", body["error"])

    def test_server_survives_errors(self):
        self.calculate({"left": "5", "op": "/", "right": "0"})
        self.assertEqual(self.calculate({"left": "1", "op": "+", "right": "1"}), (200, {"result": 2}))


class RoutingTests(ServerTestCase):
    def test_get_root_is_html(self):
        status, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn(b"<html", body)

    def test_get_root_has_calculator_controls(self):
        status, body = self.request("/")
        page = body.decode()
        self.assertEqual(status, 200)
        self.assertIn('id="display"', page)
        for digit in "0123456789.":
            with self.subTest(digit=digit):
                self.assertIn(f'data-digit="{digit}"', page)
        for op in "+-*/":
            with self.subTest(op=op):
                self.assertIn(f'data-op="{op}"', page)
        self.assertIn('id="clear"', page)
        self.assertIn('id="equals"', page)
        self.assertIn("/calculate", page)
        self.assertNotIn("eval(", page)

    def test_get_root_has_game_toggle(self):
        page = self.request("/")[1].decode()
        self.assertRegex(page, r'<button id="game-btn">Game</button>')
        self.assertRegex(page, r'<button id="back-btn">Back</button>')
        self.assertIn('<div id="game" hidden>', page)
        self.assertIn("<canvas", page)

    def test_unknown_paths_404(self):
        self.assertEqual(self.request("/tetris")[0], 404)
        self.assertEqual(self.request("/nope")[0], 404)
        self.assertEqual(self.request("/calculate")[0], 404)
        self.assertEqual(self.request("/other", "{}", "POST")[0], 404)


# Drives the embedded page script in node with a stubbed DOM; fetch goes to the real test server.
NODE_DRIVER = """
const [base, script, keys] = process.argv.slice(1);
const display = {textContent: "0"};
let onClick;
const grid = {addEventListener: (_, handler) => { onClick = handler; }};
global.document = {getElementById: (id) => (id === "display" ? display : grid)};
const realFetch = fetch;
global.fetch = (path, opts) => realFetch(base + path, opts);
(0, eval)(script);
const seen = [];
(async () => {
  for (const key of JSON.parse(keys)) {
    let el = {dataset: {digit: key}};
    if (key === "C") el = {dataset: {}, id: "clear"};
    else if (key === "=") el = {dataset: {}, id: "equals"};
    else if ("+-*/".includes(key)) el = {dataset: {op: key}};
    onClick({target: el});
    await new Promise((resolve) => setTimeout(resolve, key === "=" ? 100 : 0));
    seen.push(display.textContent);
  }
  console.log(JSON.stringify(seen));
})();
"""


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class FrontendTests(ServerTestCase):
    def press(self, keys):
        _, body = self.request("/")
        script = re.search(r"<script>(.*?)</script>", body.decode(), re.S).group(1)
        out = subprocess.run(
            ["node", "-e", NODE_DRIVER, self.base, script, json.dumps(keys)],
            capture_output=True, text=True, check=True, timeout=30,
        )
        return json.loads(out.stdout)

    def test_clicks_update_display(self):
        self.assertEqual(self.press(["1", "2", "+", "3", ".", "5", "C"]),
                         ["1", "12", "12 +", "12 + 3", "12 + 3.", "12 + 3.5", "0"])

    def test_add_shows_result(self):
        self.assertEqual(self.press(["3", "+", "4", "="])[-1], "7")

    def test_divide_by_zero_shows_error_and_server_survives(self):
        self.assertIn("division by zero", self.press(["5", "/", "0", "="])[-1])
        self.assertEqual(self.press(["1", "+", "1", "="])[-1], "2")

    def test_operator_continues_from_result(self):
        self.assertEqual(self.press(["3", "+", "4", "=", "*", "2", "="])[-3:], ["7 *", "7 * 2", "14"])

    def test_operator_after_error_is_ignored(self):
        self.assertEqual(self.press(["5", "/", "0", "=", "+", "7"])[-2:], ["0", "7"])


# Drives the second embedded script (Tetris) in node with a stubbed DOM and fake timers.
TETRIS_DRIVER = """
const script = process.argv[1];
const els = {}, listeners = {};
const el = (id) => els[id] || (els[id] = {
  id, hidden: id === "game" || id === "restart-btn", textContent: "",
  addEventListener: (type, fn) => { listeners[id + ":" + type] = fn; },
  getContext: () => ({fillRect() {}, set fillStyle(_) {}}),
});
global.document = {getElementById: el, addEventListener() {}};
let timers = 0, tick;
global.setInterval = (fn) => { timers++; tick = fn; return 1; };
global.clearInterval = () => { timers--; };
(0, eval)(script);
const out = {};
listeners["game-btn:click"]();
out.inGame = [els.calc.hidden, els.game.hidden, timers];
for (let i = 0; i < 3; i++) tick();
listeners["back-btn:click"]();
out.back = [els.calc.hidden, els.game.hidden, timers];
const T = globalThis.__tetris;
const board = T.newBoard();
board[19].fill(1);
board[18][0] = 2;
out.cleared = T.clearRows(board);
out.shifted = [board[19][0], board[19][1]];
listeners["game-btn:click"]();
for (let i = 0; i < 400 && !els["game-status"].textContent; i++) tick();
out.status = els["game-status"].textContent;
out.timersAfterOver = timers;
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TetrisTests(ServerTestCase):
    def run_game(self):
        _, body = self.request("/")
        script = re.findall(r"<script>(.*?)</script>", body.decode(), re.S)[1]
        out = subprocess.run(["node", "-e", TETRIS_DRIVER, script],
                             capture_output=True, text=True, check=True, timeout=30)
        return json.loads(out.stdout)

    def test_toggle_between_calculator_and_game(self):
        out = self.run_game()
        self.assertEqual(out["inGame"], [True, False, 1])  # calc hidden, game shown, piece timer running
        self.assertEqual(out["back"], [False, True, 0])  # calc restored, timer stopped

    def test_full_row_clears_and_rows_above_shift_down(self):
        out = self.run_game()
        self.assertEqual(out["cleared"], 1)
        self.assertEqual(out["shifted"], [2, 0])

    def test_game_over_stops_the_game(self):
        out = self.run_game()
        self.assertEqual(out["status"], "Game over")
        self.assertEqual(out["timersAfterOver"], 0)

    def test_calculate_still_adds_after_game_page_served(self):
        status, body = self.request("/calculate", json.dumps({"left": "3", "op": "+", "right": "4"}), "POST")
        self.assertEqual((status, json.loads(body)), (200, {"result": 7}))


if __name__ == "__main__":
    unittest.main()
