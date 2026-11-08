# overnight-sec-nonet-guard: evidence

Card: `overnight-sec-nonet-guard` (AGENT-8, night of 2026-11-07), filed from `overnight-sec-signoff-pack` as the next improvement in the
same area. Branch `overnight/overnight-sec-signoff-pack` (the two cards share one branch; this is the second commit). Nothing merged,
nothing pushed, no spend, no live text.

## What changed

- `tests/netguard.py` (new): importing it replaces `socket.socket.connect`, `socket.socket.connect_ex` and `socket.getaddrinfo` with versions
  that refuse any target that is not loopback, the unspecified address, `localhost` or an AF_UNIX path. A refusal raises `NetGuardError`
  (an `OSError`, so the code under test sees an ordinary connection failure), names the test suite and the target in its message, and is
  recorded in `netguard.ATTEMPTS`. Addresses are judged with `ipaddress`, so `127.0.0.1.evil.test` is a name and is refused. Bind and listen
  are untouched. `AGENTBOARD_TEST_NET=1` leaves the socket module alone for that process.
- `tests/conftest.py` (new): imports the guard, so pytest has it before collection.
- `tests/test_net_guard.py` (new, 10 tests): the guard is installed; a connect and a connect_ex to 198.51.100.1 (RFC 5737, never routed) and a
  lookup of `example.invalid` are refused before anything is sent and are recorded; the error is an `OSError`; a table of what counts as local
  (`127.9.9.9`, `::1`, `::ffff:127.0.0.1`, `LOCALHOST.`, a socket path) and not (`10.0.0.1`, `example.com`, `::ffff:10.0.0.1`, `2001:db8::1`,
  `127.0.0.1.evil.test`); a real loopback connection and a loopback lookup still work; an AF_UNIX connect fails on the OS, not the guard;
  the env switch turns it off in a fresh process. Importing `netguard` from this file is what installs the guard for `unittest discover`,
  which imports every test module before it runs the first test; the docstring says so.
- `docs/security-signoff.md`: the no-network row now cites the guard and its tests instead of a one-off manual run.
- `CHANGELOG.md`, `README.md` (Development): one entry and two sentences.

## Before / after

Before: the "makes no connection off the machine" claim rested on a manual run with a throwaway plugin (see
`overnight-sec-signoff-pack.md`), repeated only when someone thought of it. After: every run of either runner carries the guard, and a new
outbound call fails the suite with a line that says which test and which target.

## Test runs on this branch (both runners, the whole suite, guard on)

```
PYTHONPATH=src python -m pytest -q                      1196 passed, 29 subtests passed in 199.06s
PYTHONPATH=src python -m unittest discover -s tests      Ran 1196 tests in 198.424s  OK
```

Both exactly green. (The two wall-clock tests that failed in the earlier, loaded run of the sign-off card passed here; the load had dropped.)
`python3 tests/publiccheck.py`: 0 findings.

## How to try it

```
cd <worktree>; PYTHONPATH=src python3 -m pytest -q tests/test_net_guard.py        # 10 passed
PYTHONPATH=src python3 -c "import sys; sys.path.insert(0,'tests'); import netguard, socket; socket.create_connection(('198.51.100.1', 80), timeout=1)"
# -> netguard.NetGuardError: netguard: the test suite refused a non-loopback lookup to '198.51.100.1' ...
```

To see it catch a regression: add `urllib.request.urlopen("http://example.com")` to any test body and run the suite; that test errors with the
guard's message and the rest of the suite is unaffected.

## Risks

- A future test that legitimately needs the network must set `AGENTBOARD_TEST_NET=1` for its run, or mock. None exists today; the http
  provider's tests use a local server.
- The guard patches the class attribute `socket.socket.connect`; a test that replaces `socket.socket` itself (`test_doctor.py:291`,
  `test_lookup.py:185` do, with `mock.patch`) is unaffected and restores the patched class afterwards. Verified by the full runs.
- Code that resolves names without `getaddrinfo` (`gethostbyname`) is not intercepted at the lookup, but its later `connect` is.
