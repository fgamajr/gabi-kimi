#!/usr/bin/env python3
"""
TEI stub — ARM64 replacement for ghcr.io/huggingface/text-embeddings-inference.
Implements POST /embed returning 384-dim float32 vectors.
Uses hash-seeded deterministic vectors (same text → same vector).
No external dependencies.
"""
import hashlib
import json
import math
import struct
from http.server import BaseHTTPRequestHandler, HTTPServer


def text_to_vector(text: str) -> list[float]:
    """Deterministic 384-dim unit vector from SHA-256 hash of text."""
    h = hashlib.sha256(text.encode("utf-8", errors="replace")).digest()
    # Expand to 384 floats using repeated SHA-256 blocks
    raw = h
    while len(raw) < 384 * 4:
        raw += hashlib.sha256(raw).digest()
    floats = list(struct.unpack_from(f"{384}f", raw[:384 * 4]))
    # Normalize to unit sphere
    norm = math.sqrt(sum(x * x for x in floats)) or 1.0
    return [x / norm for x in floats]


class TeiHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Silence access log

    def do_GET(self):
        if self.path in ("/health", "/"):
            self._ok(b"OK")
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path != "/embed":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            payload = json.loads(body)
        except Exception:
            self.send_response(400)
            self.end_headers()
            return
        inputs = payload.get("inputs", [])
        if isinstance(inputs, str):
            inputs = [inputs]
        vectors = [text_to_vector(t) for t in inputs]
        result = json.dumps(vectors).encode()
        self._ok(result, content_type="application/json")

    def _ok(self, body: bytes, content_type: str = "text/plain"):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    print(f"TEI stub listening on :{port} (384-dim deterministic vectors)", flush=True)
    HTTPServer(("0.0.0.0", port), TeiHandler).serve_forever()
