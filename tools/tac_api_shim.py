"""Local TheAgentCompany API shim for macOS Docker smoke runs.

The official TheAgentCompany setup uses an API server with host networking.
Docker Desktop on macOS does not expose that host-networked container on the
Mac host in the same way as Linux. For one-task local evals where the actual
RocketChat/GitLab/ownCloud/Plane services are already running, this shim
provides the reset and health endpoints that task images call during init.
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class ShimHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_HEAD(self) -> None:
        self._route()

    def do_GET(self) -> None:
        self._route()

    def do_POST(self) -> None:
        self._route()

    def log_message(self, fmt: str, *args: object) -> None:
        print(fmt % args, flush=True)

    def _route(self) -> None:
        path = self.path
        if path.startswith("/api/healthcheck/"):
            self._send(200, {"message": "ok", "shim": True, "path": path})
            return
        if path.startswith("/api/reset-"):
            self._send(202, {"message": "reset accepted by local mac shim", "shim": True, "path": path})
            return
        self._send(200, {"message": "tac local shim", "shim": True})

    def _send(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a local TheAgentCompany API shim.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=2999)
    args = parser.parse_args()
    print(f"tac api shim listening on {args.host}:{args.port}", flush=True)
    ThreadingHTTPServer((args.host, args.port), ShimHandler).serve_forever()


if __name__ == "__main__":
    main()
