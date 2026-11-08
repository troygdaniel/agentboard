"""Runtime guards for the work profile: no outbound connection, no new process.

The board is built to make no outside request and start no program unless something is switched on (see lockdown.py). That is a
promise about the code. These guards turn it into something that is checked while the program runs, so a bug, a copied config file or a
future change cannot quietly break it:

    network_guard()   every way Python opens or sends on a socket refuses an address that is not this machine
                      (loopback 127.0.0.0/8 and ::1, or a Unix socket), and every name lookup refuses a name that is not "localhost";
                      listening is refused anywhere but loopback
    process_guard()   every way Python starts another program refuses (subprocess, os.system, os.popen, os.exec*, os.spawn*, os.fork)

Each returns a Guard: a context manager and a recorder. `guard.events` lists every attempt (kind, target, allowed), so `agentboard
selfcheck` can show what was tried while it exercised the server. Used as `with guard:` it is removed again on exit; `install()` keeps it
until `uninstall()`. A guard refuses with PermissionError and a message saying the work profile did it; nothing is sent first.

What this is not: a sandbox. Code in a C extension or through ctypes can open a socket without passing here, which is why selfcheck's
static scan also fails the build on any import of ctypes, cffi or a third-party package. And a program the board did not start is not
covered. The guards make the board's own promise checkable; the operating system's firewall is still the answer to a hostile process.
"""
import errno
import ipaddress
import os
import socket
import subprocess
import threading

LOCAL_NAMES = ("localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback")


class Refused(PermissionError):
    def __init__(self, what):
        super().__init__(errno.EPERM, f"agentboard work profile: {what} is not allowed on this machine")


def is_loopback(host):
    """Is `host` this machine: an address in 127.0.0.0/8 or ::1 (also ::ffff:127.x), the empty/None bind-or-connect-to-self cases excluded
    (an empty host means 'all interfaces' when binding, so it is NOT loopback here), or the name localhost."""
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if not isinstance(host, str) or not host:
        return False
    h = host.strip().lower().rstrip(".")
    if h in LOCAL_NAMES:
        return True
    h = h.strip("[]").split("%", 1)[0]
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    return ip.is_loopback


def _host_of(address):
    """(host, kind) of a socket address: a tuple (host, port, ...) is INET/INET6; a str or bytes is a Unix socket path."""
    if isinstance(address, (str, bytes)):
        return None, "unix"
    if isinstance(address, tuple) and address:
        return address[0], "inet"
    return None, "other"


class Guard:
    def __init__(self, name):
        self.name, self.events, self._patches, self._lock, self.active = name, [], [], threading.Lock(), False

    def note(self, kind, target, allowed):
        with self._lock:
            if len(self.events) < 5000:
                self.events.append((kind, str(target)[:120], allowed))

    def refused(self):
        return [e for e in self.events if not e[2]]

    def patch(self, owner, attr, new):
        self._patches.append((owner, attr, getattr(owner, attr)))
        setattr(owner, attr, new)

    def uninstall(self):
        for owner, attr, old in reversed(self._patches):
            setattr(owner, attr, old)
        self._patches, self.active = [], False

    def install(self):
        self.active = True
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.uninstall()
        return False


def network_guard(record_only=False):
    """Install the network guard and return it. With record_only the attempts are written down and still refused only if they are not local:
    the guard never lets a non-local address through, in either mode (the flag only exists for a caller that wants to look without raising,
    and it still raises: there is no mode that sends)."""
    g = Guard("network").install()
    real_connect, real_connect_ex = socket.socket.connect, socket.socket.connect_ex
    real_sendto, real_bind = socket.socket.sendto, socket.socket.bind
    real_cc, real_gai, real_gnm = socket.create_connection, socket.getaddrinfo, socket.getnameinfo
    real_ghbn, real_ghbn_ex, real_ghba = socket.gethostbyname, socket.gethostbyname_ex, socket.gethostbyaddr

    def check(kind, address):
        host, ak = _host_of(address)
        ok = ak == "unix" or (ak == "inet" and is_loopback(host))
        g.note(kind, address, ok)
        if not ok:
            raise Refused(f"{kind} to {host if ak == 'inet' else address!r}")

    def connect(self, address):
        if self.family not in (socket.AF_INET, socket.AF_INET6, getattr(socket, "AF_UNIX", -1)):
            g.note("connect", address, False)
            raise Refused(f"a connection on socket family {self.family}")
        check("connect", address)
        return real_connect(self, address)

    def connect_ex(self, address):
        check("connect_ex", address)
        return real_connect_ex(self, address)

    def sendto(self, data, *args):
        address = args[-1] if args else None
        if address is not None:
            check("sendto", address)
        return real_sendto(self, data, *args)

    def bind(self, address):
        host, ak = _host_of(address)
        ok = ak == "unix" or (ak == "inet" and is_loopback(host))
        g.note("bind", address, ok)
        if not ok:
            raise Refused(f"listening on {host!r} (only loopback may listen)")
        return real_bind(self, address)

    def create_connection(address, *a, **kw):
        host = address[0] if isinstance(address, tuple) and address else None
        ok = is_loopback(host)
        g.note("create_connection", address, ok)
        if not ok:
            raise Refused(f"a connection to {host!r}")
        return real_cc(address, *a, **kw)

    def lookup(real, kind):
        def inner(host, *a, **kw):
            ok = host is None or is_loopback(host)
            g.note(kind, host, ok)
            if not ok:
                raise Refused(f"looking up the name {host!r}")
            return real(host, *a, **kw)
        return inner

    def getnameinfo(sockaddr, flags):
        host = sockaddr[0] if isinstance(sockaddr, tuple) and sockaddr else None
        ok = is_loopback(host)
        g.note("getnameinfo", host, ok)
        if not ok:
            raise Refused(f"a reverse lookup of {host!r}")
        return real_gnm(sockaddr, flags)

    g.patch(socket.socket, "connect", connect)
    g.patch(socket.socket, "connect_ex", connect_ex)
    g.patch(socket.socket, "sendto", sendto)
    g.patch(socket.socket, "bind", bind)
    g.patch(socket, "create_connection", create_connection)
    g.patch(socket, "getaddrinfo", lookup(real_gai, "getaddrinfo"))
    g.patch(socket, "gethostbyname", lookup(real_ghbn, "gethostbyname"))
    g.patch(socket, "gethostbyname_ex", lookup(real_ghbn_ex, "gethostbyname_ex"))
    g.patch(socket, "gethostbyaddr", lookup(real_ghba, "gethostbyaddr"))
    g.patch(socket, "getnameinfo", getnameinfo)
    return g


def process_guard():
    """Install the process guard and return it: nothing may start another program."""
    g = Guard("process").install()
    real_init = subprocess.Popen.__init__

    def popen_init(self, args, *a, **kw):
        g.note("subprocess", args if isinstance(args, str) else " ".join(map(str, args)) if isinstance(args, (list, tuple)) else args, False)
        raise Refused("starting a program (subprocess)")

    g.patch(subprocess.Popen, "__init__", popen_init)

    def blocker(kind):
        def inner(*a, **kw):
            g.note(kind, a[0] if a else "", False)
            raise Refused(f"starting a program ({kind})")
        return inner

    for name in ("system", "popen", "execv", "execve", "execvp", "execvpe", "execl", "execle", "execlp", "execlpe", "posix_spawn", "posix_spawnp",
                 "spawnv", "spawnve", "spawnvp", "spawnvpe", "spawnl", "spawnle", "spawnlp", "spawnlpe", "fork", "forkpty"):
        if hasattr(os, name):
            g.patch(os, name, blocker("os." + name))
    return g
