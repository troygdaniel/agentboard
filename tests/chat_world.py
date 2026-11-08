"""The fake world for the chat end-to-end tests (card chat-q1): a throwaway board, the real server on a free loopback port, and fake SESSIONS that are
real `agentboard chat inbox --wait` processes started the way an agent starts them, which a test can leave busy, kill, duplicate or let read late.

    w = World(test)                       # in setUp
    a = w.session("AGENT-A"); a.listen()  # a session left its wait running
    m = w.owner_says("hello", to="AGENT-A")
    a.got(5)                              # what its wait printed, and how long after the line it exited (a.latency)
    w.state(m["seq"])                     # the receipt the PAGE would draw for that line (the page's own receiptOf, run in node)

Nothing here leaves this machine: the server and every process talk over 127.0.0.1 and the board's own files; no key, number or real board is read.
The page's receipt logic is not copied: `state` extracts receiptOf and its helpers from static/index.html and runs them in node, so a change to the
page that breaks a state shows here (and a page that can no longer be extracted fails loudly)."""
import json
import os
import re
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import agentboard
from agentboard import cursors, listeners, server
from agentboard.store import Store

SRC = Path(agentboard.__file__).resolve().parents[1]
PAGE = SRC / "agentboard" / "static" / "index.html"
NODE = "node"

NODE_SCRIPT = r"""
const fs = require('fs');
const page = fs.readFileSync(process.argv[2], 'utf8');
const data = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const seq = +process.argv[4], now = +process.argv[5];
function grab(re) { const m = page.match(re); if (!m) throw new Error('the page changed: cannot find ' + re); return m[0]; }
function fn(name) {
  const i = page.indexOf('function ' + name + '(');
  if (i < 0) throw new Error('the page changed: no function ' + name);
  let depth = 0, j = page.indexOf('{', i);
  for (let k = j; k < page.length; k++) { if (page[k] === '{') depth++; else if (page[k] === '}') { depth--; if (!depth) return page.slice(i, k + 1); } }
  throw new Error('unbalanced ' + name);
}
const defs = [grab(/const isOrch = [^\n]*\n/), grab(/const toOwner = [^\n]*\n/), grab(/const nameKey = [^\n]*\n/), grab(/const sameName = [^\n]*\n/),
              grab(/const RECEIPT_WARN_S = [^\n]*\n/), fn('receiptOf')].join('\n');
const run = new Function('OWNER', 'chatMsgs', 'chatReceipts', 'chatRetired', 'Date', defs + '\nreturn receiptOf(chatMsgs.find(m => m.seq === ' + seq + '));');
const FakeDate = function (...a) { return new Date(...a); };
FakeDate.now = () => now;
process.stdout.write(JSON.stringify(run(data.owner, data.messages, data.receipts, data.retired || [], FakeDate)));
"""


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def receipt_state(payload, owner, seq, now=None, workdir=None):
    """The receipt state the PAGE would draw for line `seq` of a /api/chat payload ({messages, receipts, retired}), as of `now` (epoch seconds; default now):
    the page's own receiptOf, extracted from static/index.html and run in node. Raises AssertionError when node or the page cannot do it."""
    d = Path(workdir or tempfile.mkdtemp(prefix="chat-state-"))
    (d / "payload.json").write_text(json.dumps({**payload, "owner": owner}))
    (d / "state.js").write_text(NODE_SCRIPT)
    r = subprocess.run([NODE, str(d / "state.js"), str(PAGE), str(d / "payload.json"), str(seq), str(int((now if now is not None else time.time()) * 1000))],
                       capture_output=True, text=True, timeout=30)
    if r.returncode:
        raise AssertionError("node could not run the page's receiptOf: " + r.stderr[-400:])
    return json.loads(r.stdout)


class Session:
    """One agent's terminal: the name it uses, and the wait it leaves running."""

    def __init__(self, world, name):
        self.w, self.name, self.proc, self.out, self.t_exit, self.t_start = world, name, None, b"", None, None

    def env(self):
        return {**self.w.env, "AGENTBOARD_NAME": self.name}

    def listen(self, wait=120, discard=False, drain=True):
        """Start `chat inbox --name N --wait` in the background, as an agent does. discard=True: its output goes nowhere (the reader is gone).
        drain=True first reads what is already unread (the board's own notices, such as 'agent chat is on'), as an agent does before it settles down
        to wait: a wait with something unread ends at once."""
        if drain:
            self.run("chat", "inbox", "--limit", "0")
        self.proc = subprocess.Popen([sys.executable, "-m", "agentboard", "chat", "inbox", "--name", self.name, "--wait", str(wait)], env=self.env(), cwd=self.w.cwd,
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL if discard else subprocess.PIPE, stderr=subprocess.PIPE)
        self.t_start = time.monotonic()
        self.w.cleanups.append(self.kill)
        threading.Thread(target=self._watch, daemon=True).start()
        deadline = time.time() + 15
        while time.time() < deadline and not self.listening():   # registered on the board: a line posted now will find it
            time.sleep(0.05)
        return self

    def _watch(self):
        self.proc.wait()
        self.t_exit = time.monotonic()

    def listening(self):
        return listeners.is_listening(self.w.board, self.name)   # the board's own files: this works with the server down, too

    def got(self, timeout=10):
        """What the wait printed; waits for it to end. None when it did not end in time."""
        try:
            out, err = self.proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None
        self.err = (err or b"").decode()
        return (out or b"").decode()

    def exited_after(self, t0):
        return None if self.t_exit is None else self.t_exit - t0

    def kill(self):
        if self.proc and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGKILL)
            self.proc.wait()

    def run(self, *args, cwd=None, stdin=None, env=None):
        """Any agentboard command as this name (this is what a session 'acting on the board' is). (exit code, stdout + stderr)"""
        r = subprocess.run([sys.executable, "-m", "agentboard", *args], env={**self.env(), **(env or {})}, cwd=cwd or self.w.cwd, input=stdin, capture_output=True, text=True, timeout=60)
        return r.returncode, (r.stdout + r.stderr)


class World:
    def __init__(self, test, owner="Sam", serve=True):
        self.test, self.cleanups = test, []
        self.tmp = Path(tempfile.mkdtemp(prefix="chat-e2e-"))
        test.addCleanup(self._cleanup)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.cwd = self.tmp / "elsewhere"   # sessions start in a folder with no board in it, as most do
        self.cwd.mkdir()
        self.board = self.tmp / "proj" / ".agentboard"
        self.board.mkdir(parents=True)
        (self.board / "config.toml").write_text(f'[board]\nowner = "{owner}"\n')
        self.owner = owner
        self.store = Store(self.board)
        self.store.add("seed card")
        self.port = free_port()
        self.env = {"HOME": str(self.home), "PATH": os.environ["PATH"], "PYTHONPATH": str(SRC), "PYTHONDONTWRITEBYTECODE": "1", "AGENTBOARD_DIR": str(self.board)}
        self.srv = None
        if serve:
            self.srv = server.new_server(self.store, self.port)
            threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.sessions = {}

    def _cleanup(self):
        for fn in self.cleanups:
            try:
                fn()
            except Exception:   # noqa: BLE001
                pass
        if self.srv:
            self.srv.shutdown()
            self.srv.server_close()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def session(self, name):
        s = self.sessions[name] = Session(self, name)
        return s

    # -- the owner, through the same door the page uses --------------------------------------------------------------------
    def http(self, method, path, body=None, port=None, host_extra=None):
        port = port or self.port
        data = json.dumps(body).encode() if body is not None else b""
        head = f"{method} {path} HTTP/1.1\r\nHost: localhost:{port}\r\nConnection: close\r\n" + (f"Content-Type: application/json\r\nContent-Length: {len(data)}\r\n" if method == "POST" else "") + "\r\n"
        chunks = []
        with socket.create_connection(("127.0.0.1", port), timeout=10) as s:
            s.sendall(head.encode() + data)
            while True:
                c = s.recv(65536)
                if not c:
                    break
                chunks.append(c)
        raw = b"".join(chunks)
        h, _, b = raw.partition(b"\r\n\r\n")
        status = int(h.split(b" ", 2)[1])
        return status, (json.loads(b) if b.strip().startswith((b"{", b"[")) else b.decode())

    def owner_says(self, text, to=None):
        status, m = self.http("POST", "/api/chat", {"text": text, **({"to": to} if to else {})})
        self.test.assertEqual(status, 200, m)
        return m

    def chat(self, port=None):
        status, d = self.http("GET", "/api/chat", port=port)
        self.test.assertEqual(status, 200)
        return d

    # -- the receipt the page would draw ---------------------------------------------------------------------------------------
    def state(self, seq, plus_s=0.0, payload=None):
        """The page's own receiptOf for line `seq`, as of now + plus_s seconds (the page's clock is moved, not the board's)."""
        return receipt_state(payload or self.chat(), self.owner, seq, time.time() + plus_s, workdir=self.tmp)

    # -- time travel for the board's own records ---------------------------------------------------------------------------------
    def age_delivery(self, name, seconds):
        """The delivery to `name` happened `seconds` earlier than the file says (chat-delivered.json is the only clock a delivery has)."""
        p = self.board / cursors.DELIVERED
        d = json.loads(p.read_text())
        for k, v in d.items():
            if k.lower() == name.lower():
                t = time.strptime(v["at"], "%Y-%m-%dT%H:%M:%S")
                v["at"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.mktime(t) - seconds))
        p.write_text(json.dumps(d))

    # -- commands as nobody in particular -----------------------------------------------------------------------------------------
    def cli(self, *args, cwd=None, env=None, stdin=None):
        r = subprocess.run([sys.executable, "-m", "agentboard", *args], env={**self.env, **(env or {})}, cwd=cwd or self.cwd, input=stdin, capture_output=True, text=True, timeout=60)
        return r.returncode, (r.stdout + r.stderr)

    # -- a real server process, to be killed and started again --------------------------------------------------------------------
    def serve_process(self, port=None):
        port = port or free_port()
        p = subprocess.Popen([sys.executable, "-m", "agentboard", "serve", "--no-open", "--port", str(port)], env=self.env, cwd=self.cwd, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        self.cleanups.append(lambda: p.poll() is None and (p.kill(), p.wait()))
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                if self.http("GET", "/voice.js", port=port)[0] == 200:
                    return p, port
            except OSError:
                time.sleep(0.1)
        raise AssertionError("a real server did not start")
