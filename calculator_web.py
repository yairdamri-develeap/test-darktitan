"""Local web server for the calculator.

Usage: python calculator_web.py

GET /           placeholder page
POST /calculate JSON {"left": ..., "op": ..., "right": ...}
                -> {"result": ...} or {"error": ...} (HTTP 400)
"""
import json
import math
from http.server import BaseHTTPRequestHandler, HTTPServer

from calculator import add, subtract, multiply, divide, parse_number, OPERATIONS

HOST = "127.0.0.1"
PORT = 8000
MAX_BODY = 4096

PLACEHOLDER_HTML = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Calculator</title></head>
<body><h1>Calculator</h1><p>The calculator interface is coming soon.</p></body>
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
            self._send(200, PLACEHOLDER_HTML.encode("utf-8"), "text/html; charset=utf-8")
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
        except (ValueError, UnicodeDecodeError):
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
