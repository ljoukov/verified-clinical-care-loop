"""Local, standard-library server for the Verified Clinical Care Loop demo."""

import argparse
from collections import OrderedDict
import inspect
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit

from careloop import engine, kernel, generator

STATIC = Path(__file__).parent / "static"
MAX_REQUEST = 32_000
CACHE_LIMIT = 12
verification_cache = OrderedDict()
verification_lock = Lock()


def checked(source):
    """Only cache the exact source checked under the server's fixed theory."""
    with verification_lock:
        if source in verification_cache:
            verification_cache.move_to_end(source)
            return verification_cache[source]
        result = engine.verify_source(source)
        verification_cache[source] = result
        while len(verification_cache) > CACHE_LIMIT:
            verification_cache.popitem(last=False)
        return result


class Handler(BaseHTTPRequestHandler):
    def respond(self, status, content, content_type="application/json; charset=utf-8"):
        data = json.dumps(content).encode() if isinstance(content, (dict, list)) else content
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/api/catalog":
            self.respond(200, {**engine.catalog(), "generator": generator.settings(), "generation_prompt": generator.DEFAULT_PROMPT})
        elif path == "/api/kernel":
            source = inspect.getsource(kernel.verify)
            self.respond(200, {"source": source, "verify_lines": len(source.splitlines())})
        elif path == "/api/health":
            self.respond(200, {"status": "ok", "mode": "simulation"})
        else:
            # Expose only the application assets, never project or clinical files.
            assets = {"/": ("index.html", "text/html"), "/index.html": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"), "/style.css": ("style.css", "text/css"), "/favicon.svg": ("favicon.svg", "image/svg+xml")}
            asset = assets.get(path)
            if not asset:
                self.respond(404, {"error": "Not found"})
                return
            file = STATIC / asset[0]
            if not file.is_file():
                self.respond(503, {"error": "Application asset is not ready"})
                return
            self.respond(200, file.read_bytes(), asset[1] + "; charset=utf-8")

    def do_POST(self):
        path = urlsplit(self.path).path
        if path not in ("/api/verify", "/api/evaluate", "/api/generate"):
            self.respond(404, {"error": "Not found"})
            return
        # Keep the local API same-origin. No arbitrary Python is ever executed.
        origin = self.headers.get("Origin")
        if origin and origin != "http://" + self.headers.get("Host", ""):
            self.respond(403, {"error": "Cross-origin requests are not allowed"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_REQUEST:
                self.respond(413, {"error": "Request is empty or too large"})
                return
            if self.headers.get_content_type() != "application/json":
                self.respond(415, {"error": "Use application/json"})
                return
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("Request must be a JSON object")
            if path == "/api/generate":
                self.respond(200, generator.generate(payload.get("prompt", generator.DEFAULT_PROMPT)))
                return
            source = payload.get("source")
            if not isinstance(source, str) or not source.strip() or len(source) > 12_000:
                raise ValueError("Provide a program of at most 12,000 characters")
            verification = checked(source)
            if path == "/api/verify":
                self.respond(200, verification)
                return
            if not verification.get("valid"):
                self.respond(422, {"error": "Execution blocked: this exact source has no accepted proof."})
                return
            state = payload.get("state")
            if not isinstance(state, dict):
                raise ValueError("State must be an object with all eight Boolean fields")
            fields = {"final", "authorised", "current", "susceptible", "exception", "family", "access", "overdue"}
            if set(state) != fields or any(type(value) is not bool for value in state.values()):
                raise ValueError("State must contain exactly the eight Boolean model fields")
            result = engine.evaluate(source, state)
            self.respond(200, {**result, "code_hash": verification["code_hash"], "simulated": True})
        except (ValueError, TypeError, RecursionError) as error:
            self.respond(400, {"error": str(error)})
        except Exception:
            self.log_error("Internal error while processing %s", path)
            self.respond(500, {"error": "The checker could not complete this request. Execution remains blocked."})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Verified Clinical Care Loop: http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
