#!/bin/bash
# usage: bash tests/qa/cleanroom.sh <scratch dir>   (needs pipx, python3.11-3.14 on PATH, curl; network for the online steps)
# Clean-room install as a stranger: fresh HOME, fresh pipx, fresh venvs, README commands verbatim. Logs PASS/FAIL per step.
SRC="$(cd "$(dirname "$0")/../.." && pwd)"   # this checkout
ROOT="$1"; rm -rf "$ROOT"; mkdir -p "$ROOT/home"
LOG="$ROOT/steps.log"; : > "$LOG"
step() { local name="$1"; shift; if "$@" >"$ROOT/$(echo "$name" | tr ' /' '__').out" 2>&1; then echo "PASS  $name" | tee -a "$LOG"; else echo "FAIL  $name (exit $?)" | tee -a "$LOG"; fi; }
export HOME="$ROOT/home"
export PIPX_HOME="$HOME/.local/pipx" PIPX_BIN_DIR="$HOME/.local/bin"
export PATH="$PIPX_BIN_DIR:/opt/homebrew/bin:/usr/bin:/bin"
for v in $(env | grep -o '^AGENTBOARD_[A-Z_]*'); do unset "$v"; done
cd "$ROOT"
step "clone (local stand-in for the GitHub clone)" git clone -q "$SRC" clone
cd clone
step "offline: pipx install . with PIP_NO_INDEX=1" env PIP_NO_INDEX=1 pipx install .
pipx uninstall agentboard >/dev/null 2>&1
step "pipx install . (network allowed)" pipx install .
step "agentboard --version prints 0.3.1" bash -c 'agentboard --version | grep -qx 0.3.1'
mkdir -p proj && cd proj && git init -q .
step "agentboard init" agentboard init
step "init made .agentboard/tasks.json and config.toml" bash -c 'test -f .agentboard/tasks.json && test -f .agentboard/config.toml'
step "init added .agentboard/ to .gitignore" bash -c 'grep -q agentboard .gitignore'
step "agentboard doctor" agentboard doctor
step "agentboard instructions" agentboard instructions
step "card flow: add, claim, start, update, review, done" bash -c '
  agentboard add "first card" && agentboard claim --name AGENT-1 first-card && agentboard update first-card 50 "half" && agentboard review first-card "look" && agentboard done first-card && agentboard list | grep -q "first-card"'
agentboard serve --no-open --port 8799 > serve.log 2>&1 &
SPID=$!; sleep 3
step "serve: / answers 200" bash -c 'curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8799/ | grep -qx 200'
step "serve: /hud answers 200" bash -c 'curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8799/hud | grep -qx 200'
step "serve: /api/state is JSON" bash -c 'curl -s http://127.0.0.1:8799/api/state | python3 -c "import json,sys; json.load(sys.stdin)"'
step "serve: listens on 127.0.0.1 only" bash -c 'lsof -nP -iTCP:8799 -sTCP:LISTEN | grep -q "127.0.0.1:8799" && ! lsof -nP -iTCP:8799 -sTCP:LISTEN | grep -q "\*:8799"'
step "serve: a second serve on the same port says so" bash -c '! timeout 10 agentboard serve --no-open --port 8799 2>&1 | head -5 | grep -qi traceback'
kill $SPID 2>/dev/null; wait $SPID 2>/dev/null
step "serve log has no Traceback" bash -c '! grep -q Traceback serve.log'
cd ..
step "upgrade: rm -rf build && pipx install . --force" bash -c 'rm -rf build && pipx install . --force'
step "hooks install in a project" bash -c 'cd proj && agentboard hooks install && test -f .claude/settings.json'
step "pipx uninstall agentboard" pipx uninstall agentboard
step "after uninstall the command is gone" bash -c '! command -v agentboard'
for py in python3.11 python3.12 python3.13 python3.14; do
  step "venv path offline ($py): venv + PIP_NO_INDEX=1 pip install ." bash -c "rm -rf build && $py -m venv $HOME/venv-off-$py && PIP_NO_INDEX=1 $HOME/venv-off-$py/bin/pip install -q . "
  step "venv path ($py): README venv + pip install . + --version" bash -c "rm -rf build && $py -m venv $HOME/venv-$py && $HOME/venv-$py/bin/pip install -q . && $HOME/venv-$py/bin/agentboard --version | grep -qx 0.3.1"
done
step "clone left no build/ dir after README venv installs" bash -c '! test -d build || ls build'
step "publiccheck on the clone" python3 tests/publiccheck.py .
echo "DONE" >> "$LOG"
