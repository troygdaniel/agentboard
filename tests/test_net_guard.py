"""The suite's network guard (tests/netguard.py) trips on anything that would leave the machine and lets loopback through.

Importing netguard here is what installs the guard for `unittest discover` (every test module is imported before the first test runs),
so this file must keep that import whatever else changes."""
import os
import socket
import tempfile
import threading
import unittest
from pathlib import Path

import netguard

TEST_NET_2 = "198.51.100.1"   # RFC 5737: documentation only, never routed; the guard must refuse it before any packet is sent


class TheGuardIsOn(unittest.TestCase):
    def test_installed_for_this_run(self):
        self.assertTrue(netguard.active(), "the guard did not install: is AGENTBOARD_TEST_NET set?")
        self.assertNotEqual(socket.socket.connect.__module__, "socket", "socket.connect is the original: the guard is not in place")


class WhatIsRefused(unittest.TestCase):
    def setUp(self):
        del netguard.ATTEMPTS[:]

    def test_a_connect_to_a_routable_address_is_refused_before_it_leaves(self):
        with socket.socket() as s:
            s.settimeout(0.2)
            with self.assertRaises(netguard.NetGuardError) as cm:
                s.connect((TEST_NET_2, 80))
        self.assertIn("netguard", str(cm.exception))
        self.assertIn(TEST_NET_2, str(cm.exception))
        self.assertEqual(netguard.ATTEMPTS, [("connect", (TEST_NET_2, 80))])

    def test_connect_ex_is_refused_the_same_way(self):
        with socket.socket() as s:
            with self.assertRaises(netguard.NetGuardError):
                s.connect_ex((TEST_NET_2, 443))
        self.assertEqual(netguard.ATTEMPTS[0][0], "connect_ex")

    def test_a_name_lookup_of_an_outside_host_is_refused(self):
        with self.assertRaises(netguard.NetGuardError):
            socket.getaddrinfo("example.invalid", 443)
        self.assertEqual(netguard.ATTEMPTS, [("lookup", "example.invalid")])

    def test_the_refusal_is_an_oserror_so_code_under_test_sees_a_connection_failure(self):
        self.assertTrue(issubclass(netguard.NetGuardError, OSError))

    def test_what_counts_as_local(self):
        for addr in (("127.0.0.1", 8765), ("localhost", 1), ("::1", 1, 0, 0), ("0.0.0.0", 1), ("127.9.9.9", 1), ("::ffff:127.0.0.1", 1),
                     ("LOCALHOST.", 1), "/tmp/some.sock", b"/tmp/some.sock"):
            self.assertTrue(netguard.allowed(addr), addr)
        for addr in ((TEST_NET_2, 80), ("10.0.0.1", 22), ("example.com", 443), ("::ffff:10.0.0.1", 1), ("2001:db8::1", 1, 0, 0), ("127.0.0.1.evil.test", 1)):
            self.assertFalse(netguard.allowed(addr), addr)


class WhatStillWorks(unittest.TestCase):
    def test_a_loopback_connection_goes_through(self):
        with socket.socket() as srv:
            srv.bind(("127.0.0.1", 0))
            srv.listen(1)
            port = srv.getsockname()[1]
            got = []
            t = threading.Thread(target=lambda: got.append(srv.accept()[0]))
            t.start()
            with socket.create_connection(("127.0.0.1", port), timeout=5) as c:
                c.sendall(b"hi")
            t.join(5)
            for s in got:
                s.close()
        self.assertEqual(len(got), 1)

    def test_a_unix_socket_path_is_local(self):
        with tempfile.TemporaryDirectory() as d, socket.socket(socket.AF_UNIX) as s:
            with self.assertRaises(FileNotFoundError):   # refused by the OS (no such file), not by the guard
                s.connect(str(Path(d) / "none.sock"))
        self.assertNotIn(("connect", str(Path(d) / "none.sock")), netguard.ATTEMPTS)

    def test_a_lookup_of_a_local_name_goes_through(self):
        self.assertTrue(socket.getaddrinfo("127.0.0.1", 80))
        self.assertTrue(socket.getaddrinfo(None, 80))

    def test_the_switch_is_named_and_the_env_turns_it_off_for_a_fresh_process(self):
        self.assertEqual(netguard.ENV, "AGENTBOARD_TEST_NET")
        import subprocess, sys
        code = "import sys; sys.path.insert(0, %r); import netguard; print(netguard.active())" % str(Path(__file__).parent)
        out = subprocess.run([sys.executable, "-c", code], env={**os.environ, netguard.ENV: "1"}, capture_output=True, text=True, timeout=30)
        self.assertEqual(out.stdout.strip(), "False", out.stderr)


if __name__ == "__main__":
    unittest.main()
