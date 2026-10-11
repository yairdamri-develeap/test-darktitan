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

    def test_get_root_has_flappy_button(self):
        page = self.request("/")[1].decode()
        self.assertRegex(page, r'<button id="flappy-btn">Flappy Bird</button>')

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


# Drives the third embedded script (Flappy Bird) in node with a stubbed DOM and fake timers.
# The Tetris script is not loaded; a stub __tetris records whether Flappy Bird stopped it.
FLAPPY_DRIVER = """
const script = process.argv[1];
const els = {}, listeners = {};
const el = (id) => els[id] || (els[id] = {
  id, hidden: id === "game" || id === "restart-btn", textContent: "",
  addEventListener: (type, fn) => { (listeners[id + ":" + type] ||= []).push(fn); },
  getContext: () => ({fillRect() {}, set fillStyle(_) {}}),
});
const fire = (key, ...args) => (listeners[key] || []).forEach((fn) => fn(...args));
global.document = {getElementById: el, addEventListener: (type, fn) => {
  (listeners["document:" + type] ||= []).push(fn);
}};
let timers = 0, tick;
global.setInterval = (fn) => { timers++; tick = fn; return 1; };
global.clearInterval = () => { timers--; };
let tetrisStops = 0;
globalThis.__tetris = {stop() { tetrisStops++; }};
(0, eval)(script);
const F = globalThis.__flappybird;
const out = {};
fire("flappy-btn:click");
out.inGame = [els.calc.hidden, els.game.hidden, timers];
out.tetrisStops = tetrisStops;
// the bird falls under gravity
const bird = {y: 100, vy: 0};
F.applyGravity(bird);
const fell = bird.y > 100;
F.applyGravity(bird);
out.falling = fell && bird.vy > 0 && bird.y > 101;
// flap via spacebar and via canvas click
F.flap(bird);
out.flapVy = bird.vy < 0;
const key = {key: " ", preventDefault() { this.prevented = true; }};
fire("document:keydown", key);
out.spacePrevented = !!key.prevented;
fire("board:click");
out.helpers = [
  F.outOfBounds({y: -1}), F.outOfBounds({y: 390}), F.outOfBounds({y: 200}),
  F.hitsPipe({y: 200}, [{x: 50, gapY: 10}]),
  F.hitsPipe({y: 20}, [{x: 50, gapY: 10}]),
  F.hitsPipe({y: 200}, [{x: 150, gapY: 10}]),
];
// no flapping: the bird hits the bottom (or a pipe) and the game ends
for (let i = 0; i < 400 && !els["game-status"].textContent; i++) tick();
out.status = els["game-status"].textContent;
out.timersAfterOver = timers;
// restart with spacebar
fire("document:keydown", key);
out.restarted = [els["game-status"].textContent, timers];
// Tetris launch stops Flappy Bird
fire("game-btn:click");
out.timersAfterTetris = timers;
fire("document:keydown", key);
out.inactiveIgnoresSpace = timers;
// back stops it too
fire("flappy-btn:click");
fire("back-btn:click");
out.timersAfterBack = timers;
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class FlappyTests(ServerTestCase):
    def run_game(self):
        _, body = self.request("/")
        script = re.findall(r"<script>(.*?)</script>", body.decode(), re.S)[2]
        out = subprocess.run(["node", "-e", FLAPPY_DRIVER, script],
                             capture_output=True, text=True, check=True, timeout=30)
        return json.loads(out.stdout)

    def test_toggle_stops_tetris_and_starts_game(self):
        out = self.run_game()
        self.assertEqual(out["inGame"], [True, False, 1])  # calc hidden, game shown, timer running
        self.assertEqual(out["tetrisStops"], 1)
        self.assertEqual(out["timersAfterBack"], 0)

    def test_gravity_and_flap(self):
        out = self.run_game()
        self.assertTrue(out["falling"])
        self.assertTrue(out["flapVy"])
        self.assertTrue(out["spacePrevented"])

    def test_collision_helpers(self):
        self.assertEqual(self.run_game()["helpers"], [True, True, False, True, False, False])

    def test_game_over_stops_the_timer_and_restart_works(self):
        out = self.run_game()
        self.assertIn("Game over", out["status"])
        self.assertEqual(out["timersAfterOver"], 0)
        self.assertEqual(out["restarted"], ["", 1])

    def test_launching_tetris_stops_flappy_bird(self):
        out = self.run_game()
        self.assertEqual(out["timersAfterTetris"], 0)
        self.assertEqual(out["inactiveIgnoresSpace"], 0)


if __name__ == "__main__":
    unittest.main()
