"""Local web server for the calculator.

Usage: python calculator_web.py

GET /           calculator page (embedded HTML/JS)
POST /calculate JSON {"left": ..., "op": ..., "right": ...}
                -> {"result": ...} or {"error": ...} (HTTP 400)
"""
import json
import math
from http.server import BaseHTTPRequestHandler, HTTPServer

from calculator import add, subtract, multiply, divide, parse_number, OPERATIONS  # noqa: F401

HOST = "127.0.0.1"
PORT = 8000
MAX_BODY = 4096

INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Calculator</title>
<style>
  body { font-family: sans-serif; background: #eceff1; display: flex; justify-content: center; padding-top: 3em; }
  #calc { width: 18em; background: #fff; padding: 1em; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,.25); }
  #display { min-height: 1.5em; margin-bottom: .75em; padding: .5em; background: #263238; color: #fff;
             font-size: 1.5em; text-align: right; overflow-wrap: anywhere; border-radius: 4px; }
  #grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: .4em; }
  button { font-size: 1.25em; padding: .6em 0; border: 0; border-radius: 4px; background: #cfd8dc; cursor: pointer; }
  button:hover { background: #b0bec5; }
  button.op { background: #ff9800; }
  button.op:hover { background: #fb8c00; }
  button.eq { background: #43a047; color: #fff; grid-column: 1 / -1; }
  button.clear { background: #e53935; color: #fff; }
</style>
</head>
<body>
<div id="calc">
  <div id="display">0</div>
  <div id="grid">
    <button data-digit="7">7</button>
    <button data-digit="8">8</button>
    <button data-digit="9">9</button>
    <button class="op" data-op="/">/</button>
    <button data-digit="4">4</button>
    <button data-digit="5">5</button>
    <button data-digit="6">6</button>
    <button class="op" data-op="*">*</button>
    <button data-digit="1">1</button>
    <button data-digit="2">2</button>
    <button data-digit="3">3</button>
    <button class="op" data-op="-">-</button>
    <button data-digit="0">0</button>
    <button data-digit=".">.</button>
    <button class="clear" id="clear">C</button>
    <button class="op" data-op="+">+</button>
    <button class="eq" id="equals">=</button>
  </div>
</div>
<script>
(function () {
  var left = "", op = "", right = "", shown = null;
  var display = document.getElementById("display");

  function render() {
    if (shown !== null) { display.textContent = shown; return; }
    var text = [left, op, right].filter(Boolean).join(" ");
    display.textContent = text || "0";
  }

  function reset() { left = ""; op = ""; right = ""; shown = null; }

  function digit(d) {
    if (shown !== null) { reset(); }
    var current = op ? right : left;
    if (d === "." && current.indexOf(".") !== -1) { return; }
    if (op) { right += d; } else { left += d; }
  }

  function operator(o) {
    if (shown !== null) { left = shown; shown = null; }
    if (!left) { return; }
    if (op && right) { return; }
    op = o;
  }

  function equals() {
    if (!left || !op || !right) { return; }
    var body = JSON.stringify({ left: left, op: op, right: right });
    fetch("/calculate", { method: "POST", headers: { "Content-Type": "application/json" }, body: body })
      .then(function (resp) { return resp.json(); })
      .then(function (data) {
        reset();
        shown = data.result !== undefined ? String(data.result) : "Error: " + data.error;
        render();
      })
      .catch(function () { reset(); shown = "Error: network error"; render(); });
  }

  document.getElementById("grid").addEventListener("click", function (event) {
    var el = event.target;
    if (el.dataset.digit !== undefined) { digit(el.dataset.digit); }
    else if (el.dataset.op !== undefined) { operator(el.dataset.op); }
    else if (el.id === "clear") { reset(); }
    else if (el.id === "equals") { equals(); return; }
    else { return; }
    render();
  });
})();
</script>
</body>
</html>
"""


class CalculatorHandler(BaseHTTPRequestHandler):
    def _send(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status, obj):
        self._send(status, json.dumps(obj).encode("utf-8"), "application/json")

    def _error(self, message, status=400):
        self._send_json(status, {"error": message})

    def do_GET(self):
        if self.path == "/":
            self._send(200, INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
        else:
            self._error("not found", 404)

    def do_POST(self):
        if self.path != "/calculate":
            self._error("not found", 404)
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._error("missing or invalid Content-Length")
            return
        if length < 0 or length > MAX_BODY:
            self._error("request body too large")
            return
        try:
            data = json.loads(self.rfile.read(length))
        except ValueError:
            self._error("invalid JSON")
            return
        if not isinstance(data, dict):
            self._error("request body must be a JSON object")
            return
        for field in ("left", "op", "right"):
            if field not in data:
                self._error(f"missing field '{field}'")
                return
        op = data["op"]
        if not isinstance(op, str) or op not in OPERATIONS:
            self._error(f"unknown operator '{op}'")
            return
        operands = []
        for field in ("left", "right"):
            value = data[field]
            try:
                if isinstance(value, bool) or not isinstance(value, (str, int, float)):
                    raise ValueError(value)
                operands.append(parse_number(str(value)))
            except ValueError:
                self._error(f"invalid number '{value}'")
                return
        try:
            result = OPERATIONS[op](*operands)
        except ZeroDivisionError:
            self._error("division by zero")
            return
        except OverflowError:
            self._error("result too large")
            return
        if isinstance(result, float) and not math.isfinite(result):
            self._error("result too large")
            return
        self._send_json(200, {"result": result})


def main(host=HOST, port=PORT):
    server = HTTPServer((host, port), CalculatorHandler)
    print(f"Serving calculator at http://{host}:{server.server_address[1]}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
