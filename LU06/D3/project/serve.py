#!/usr/bin/env python3
"""Serve the frontend and relay requests to local Ollama. No dependencies."""
import json
import socket
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MOVES = {"rock", "paper", "scissors"}

def valid_game(game):
    return (isinstance(game, dict) and set(game) == {"human", "ai", "winner"}
            and game["human"] in MOVES and game["ai"] in MOVES
            and game["winner"] in {"human", "ai", "tie"})

class Handler(BaseHTTPRequestHandler):
    def send_json(self, code, data):
        content = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        if self.path not in ("/", "/index.html"):
            self.send_error(404)
            return
        content = (ROOT / "index.html").read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self):
        if self.path != "/api/play":
            self.send_error(404)
            return
        origin = self.headers.get("Origin")
        if origin and origin not in {"http://127.0.0.1:8000", "http://localhost:8000"}:
            self.send_json(403, {"error": "Open the game at http://127.0.0.1:8000."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 2_000_000:
                raise ValueError("Invalid request size.")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict) or set(data) != {"last_game", "previous_games"}:
                raise ValueError("Expected last_game and previous_games.")
            previous = data["previous_games"]
            if not isinstance(previous, list) or not all(valid_game(g) for g in previous):
                raise ValueError("Invalid previous_games.")
            if data["last_game"] == "start":
                if previous:
                    raise ValueError("A new game must have empty history.")
            elif not valid_game(data["last_game"]):
                raise ValueError("Invalid last_game.")
            request_body = {
                "model": "rpc:latest", "prompt": json.dumps(data, separators=(",", ":")),
                "stream": False, "think": False, "keep_alive": "10m",
                "format": {"type": "object", "properties": {"ai": {
                    "type": "string", "enum": ["rock", "paper", "scissors"]}},
                    "required": ["ai"], "additionalProperties": False},
                "options": {"num_predict": 32},
            }
            request = urllib.request.Request("http://127.0.0.1:11434/api/generate",
                data=json.dumps(request_body).encode(),
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(request, timeout=90) as response:
                result = json.load(response)
            if not result.get("done"):
                raise ValueError("Ollama did not finish generating a move.")
            move = json.loads(result.get("response", ""))
            if not isinstance(move, dict) or set(move) != {"ai"} or move["ai"] not in MOVES:
                raise ValueError('Expected {"ai":"rock"}, {"ai":"paper"}, or {"ai":"scissors"}.')
            self.send_json(200, move)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            try:
                detail = json.loads(detail).get("error", detail)
            except (ValueError, AttributeError):
                pass
            self.send_json(502, {"error": f"Ollama HTTP {exc.code}: {str(detail)[:500]}"})
        except (urllib.error.URLError, socket.timeout, TimeoutError):
            self.send_json(503, {"error": "Cannot reach Ollama or the request timed out. Start Ollama and check that the rpc model is installed (ollama list)."})
        except (ValueError, TypeError, KeyError) as exc:
            self.send_json(400, {"error": str(exc)})

if __name__ == "__main__":
    print("Rock Paper Scissors: http://127.0.0.1:8000", flush=True)
    print("Ollama model: rpc at 127.0.0.1:11434. Ctrl+C to stop.", flush=True)
    try:
        ThreadingHTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
