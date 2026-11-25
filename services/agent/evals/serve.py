"""Local server for the eval viewer: serves the page and saved results, and can start a new eval run.

    make eval-view        # http://localhost:8090/viewer/

Only listens on 127.0.0.1. Starting a run costs money (it calls the real model), so the run endpoint
also refuses requests from other websites: it needs a custom header, which browsers only send cross-site
after a CORS preflight that this server never approves, and the Host must be this server (DNS rebinding).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
PORT = int(os.getenv("EVAL_VIEW_PORT", "8090"))
MODELS = ["gpt-5.5", "gpt-5.4"]
CASE_SETS = {"all": [], "core": ["core"], "adversarial": ["adversarial"]}  # arguments for evals.run


class Runner:
    """At most one eval run at a time; keeps its output for the progress view."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.proc: subprocess.Popen | None = None
        self.lines: list[str] = []
        self.started = 0.0
        self.model = ""
        self.exit_code: int | None = None

    def status(self) -> dict:
        running = self.proc is not None and self.proc.poll() is None
        return {"running": running, "model": self.model, "exit_code": None if running else self.exit_code,
                "seconds": round(time.time() - self.started) if self.started else 0, "lines": self.lines[-200:]}

    def start(self, model: str, case_set: str, with_failure: bool = False) -> bool:
        with self.lock:
            if self.proc is not None and self.proc.poll() is None:
                return False
            env = {**os.environ, "LLM_MODEL": model, "PYTHONUNBUFFERED": "1"}
            self.lines, self.started, self.model, self.exit_code = [], time.time(), model, None
            args = [*CASE_SETS[case_set], *(["deliberate_failure"] if with_failure else [])]
            self.proc = subprocess.Popen([sys.executable, "-m", "evals.run", *args], cwd=HERE.parent, env=env,
                                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()
            return True

    def _read(self, proc: subprocess.Popen) -> None:
        assert proc.stdout
        for line in proc.stdout:
            line = line.rstrip()
            if line and " INFO " not in line:  # the services' request logs are noise here
                self.lines.append(line)
        self.exit_code = proc.wait()


runner = Runner()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(HERE), **kwargs)

    def log_message(self, fmt, *args):  # keep the terminal quiet
        pass

    def _json(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("cache-control", "no-store")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _same_site(self) -> bool:
        host_ok = self.headers.get("host") in (f"localhost:{PORT}", f"127.0.0.1:{PORT}")
        origin = self.headers.get("origin")
        origin_ok = origin is None or origin in (f"http://localhost:{PORT}", f"http://127.0.0.1:{PORT}")
        return host_ok and origin_ok and self.headers.get("x-eval-viewer") == "1"

    def do_GET(self):
        if self.path == "/":
            self.send_response(302)
            self.send_header("location", "/viewer/")
            self.end_headers()
        elif self.path == "/api/status":
            self._json(200, {**runner.status(), "models": MODELS, "case_sets": list(CASE_SETS)})
        else:
            super().do_GET()

    def do_POST(self):
        if self.path != "/api/run":
            return self._json(404, {"error": "not found"})
        if not self._same_site():
            return self._json(403, {"error": "Runs can only be started from the viewer itself."})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
        except ValueError:
            body = {}
        model = body.get("model") or MODELS[0]
        if model not in MODELS:
            return self._json(400, {"error": f"Unknown model {model!r}"})
        case_set = body.get("cases") or "all"
        if case_set not in CASE_SETS:
            return self._json(400, {"error": f"Unknown case set {case_set!r}"})
        if not runner.start(model, case_set, bool(body.get("deliberate_failure"))):
            return self._json(409, {"error": "A run is already in progress."})
        self._json(202, runner.status())


if __name__ == "__main__":
    print(f"Eval viewer: http://localhost:{PORT}/viewer/  (Ctrl+C to stop)")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
