"""pytest loads this before collecting: the network guard is on for every test (tests/netguard.py). `unittest discover` gets the same
guard through tests/test_net_guard.py, which imports the module before any test runs."""
import netguard  # noqa: F401  (importing installs the guard)
