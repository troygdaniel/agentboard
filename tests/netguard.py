"""The test suite never leaves the machine: importing this module makes every non-loopback socket connection fail, loudly.

agentboard's security story says the board makes no network connection beyond 127.0.0.1 unless you switch an opt-in feature on. The
suite proved that by hand once (a guard plugin, see docs/overnight/overnight-sec-signoff-pack.md); this module makes it true on every run,
so a change that adds an outbound call fails the suite the same day instead of waiting for the next audit.

How: `socket.socket.connect`, `socket.socket.connect_ex` and `socket.getaddrinfo` are replaced by versions that refuse any target that is
not loopback (127.0.0.0/8, ::1, localhost, the unspecified address) or an AF_UNIX path. A refusal raises `NetGuardError` (an OSError, so
the code under test sees an ordinary connection failure and the test that caused it fails or errors with this module's name in the
message) and is recorded in `ATTEMPTS`. Bind and listen are untouched: the server tests still start their own loopback listeners.

Both runners load it before any test runs: `tests/conftest.py` imports it for pytest; `tests/test_net_guard.py` imports it for
`unittest discover`, which imports every test module before it runs the first test. Set AGENTBOARD_TEST_NET=1 to switch the guard off
for a run that must reach the network on purpose (nothing in this suite does)."""
import ipaddress
import os
import socket

ENV = "AGENTBOARD_TEST_NET"
ATTEMPTS = []   # (what, target) for every refusal, in order


class NetGuardError(OSError):
    pass


def host_of(address):
    """The host part of a connect() address, or None for an AF_UNIX path (always local)."""
    if isinstance(address, (str, bytes, os.PathLike)):
        return None
    try:
        return str(address[0])
    except (TypeError, IndexError, KeyError):
        return str(address)


def allowed(address):
    """True for loopback, the unspecified address, 'localhost' and AF_UNIX paths; False for anything that could leave the machine."""
    host = host_of(address)
    return host is None or allowed_host(host)


def allowed_host(host):
    """An address is local when it parses as loopback or the unspecified address (IPv4-mapped IPv6 included); a name only when it is
    'localhost' or empty. '127.0.0.1.evil.test' is a name, not an address, and is refused."""
    h = str(host).strip().lower().rstrip(".")
    if h.startswith("[") and h.endswith("]"):
        h = h[1:-1]
    if "%" in h:   # fe80::1%lo0 style scope: judge the address alone
        h = h.split("%", 1)[0]
    if h in ("", "localhost"):
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_loopback or ip.is_unspecified


def _refuse(what, target):
    ATTEMPTS.append((what, target))
    raise NetGuardError(f"netguard: the test suite refused a non-loopback {what} to {target!r}; agentboard never leaves the machine "
                        f"(tests/netguard.py; set {ENV}=1 for a run that must)")


_installed = False
_orig = {}


def install():
    """Patch the socket module once. Returns True when the guard is active after the call."""
    global _installed
    if _installed:
        return True
    if os.environ.get(ENV, "").strip() == "1":
        return False
    _orig["connect"], _orig["connect_ex"], _orig["getaddrinfo"] = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo

    def connect(self, address):
        if not allowed(address):
            _refuse("connect", address)
        return _orig["connect"](self, address)

    def connect_ex(self, address):
        if not allowed(address):
            _refuse("connect_ex", address)
        return _orig["connect_ex"](self, address)

    def getaddrinfo(host, *args, **kwargs):
        if host is not None and not allowed_host(host if not isinstance(host, bytes) else host.decode(errors="replace")):
            _refuse("lookup", host)
        return _orig["getaddrinfo"](host, *args, **kwargs)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.getaddrinfo = getaddrinfo
    _installed = True
    return True


def active():
    return _installed


install()
