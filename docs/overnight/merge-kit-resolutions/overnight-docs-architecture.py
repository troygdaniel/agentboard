"""docs-architecture x main in README.md: two paragraphs added at the same spot (main's network-guard note, the branch's pointer to
ARCHITECTURE.md and CONTRIBUTING.md): keep both, main's first. (CHANGELOG is the kit's own rule.)"""
import sys
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from _lib import both, resolve   # noqa: E402

ok = resolve(sys.argv[1], "README.md", lambda ours, theirs: ours.rstrip("\n") + "\n\n" + theirs)
sys.exit(0 if ok else 1)
