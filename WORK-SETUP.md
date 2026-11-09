# agentboard on a work computer

One page. If you use Claude Code at work, tell it: "Read WORK-SETUP.md and set agentboard up."

## 1. Install (Python 3.11+ is all you need)

With internet, from a checkout:

    rm -rf build && pipx install .

No internet or no admin rights: on any machine with network, make one file, then carry it over.

    python3 -m pip wheel --no-deps -w dist .          # makes dist/agentboard-<version>-py3-none-any.whl

On the work computer:

    python3 -m venv ~/.agentboard-venv && ~/.agentboard-venv/bin/pip install --no-index dist/agentboard-*-py3-none-any.whl
    export PATH="$HOME/.agentboard-venv/bin:$PATH"

Check: `agentboard --version`.

## 2. Make it safe for work

    cd your-project
    agentboard init            # on a machine with no home setup this picks the work profile by itself
    agentboard profile work    # loopback only, no outside requests, no plugins, no programs started
    agentboard selfcheck       # every line should say PASS
    agentboard doctor          # want: no FAIL

## 3. Run it

    agentboard serve           # http://localhost:8765, Ctrl+C stops

Agents use the `agentboard` command from other terminals in the same project folder.
To give them the protocol, run `agentboard init --instructions` (it adds the agent instructions to the project's `CLAUDE.md`).

## 4. For the security reviewer

Send `docs/security-signoff.md` (two pages, each claim cites the file and the test) plus the output of `agentboard selfcheck`.
No dependencies, listens on 127.0.0.1 only, writes only inside `.agentboard/`.

## If something goes wrong

- `agentboard doctor` says what is wrong and how to fix it.
- A stale install after a `git pull`: `rm -rf build` and install again.
- Remove everything: see "Uninstall" in `README.md`.
- Texts, Facts and the microphone are not part of this repo. They live in a private home plugin and do not exist on the work computer.
