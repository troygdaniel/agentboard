#!/usr/bin/env bash
# merge-kit.sh: a DRY-RUN merge of the overnight/* branches, in AGENT-8's recommended order, inside a THROWAWAY clone.
#
# It never touches the checkout it is run from, any worktree, or a board: everything happens in a fresh clone under a temp folder
# (printed at the start, kept at the end for a look, deleted by --clean). Nothing is pushed. For each branch in order it merges with
# --no-ff, auto-resolves a conflict in CHANGELOG.md only (both sections kept, the branch's first), and at any other conflict prints the
# files, the conflicting hunks and a suggested resolution, aborts that merge and goes on to the next branch (so one bad merge does not
# hide the rest). When docs/overnight/merge-kit-resolutions/<branch slug>.py exists it is run inside the clone first (the resolution that
# worked in the night's dry run); the merge lands only if it leaves no conflict marker. After every merge that lands it runs the page-script check (the <script> of index.html must parse) and the full suite,
# and at the end prints one table: branch, merged yes/no, tests, notes. --out writes the same table as markdown.
#
#   docs/overnight/merge-kit.sh                                  # the default order, full suite after each merge (about an hour)
#   docs/overnight/merge-kit.sh --quick                          # page-script check and py_compile only, no suites (minutes)
#   docs/overnight/merge-kit.sh --order my-order.txt             # one branch name per line (# comments allowed)
#   docs/overnight/merge-kit.sh --main main --out docs/overnight/merge-kit-dry-run.md --clean
#
# Exit code: 0 when every branch in the order merged and every suite passed; 1 otherwise (the table says which).
set -u

REPO="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"     # where the branches live; read only
MAIN="main"
ORDER_FILE=""
OUT=""
QUICK=0
CLEAN=0
PY="${MERGE_KIT_PYTHON:-}"
while [ $# -gt 0 ]; do
  case "$1" in
    --main) MAIN="$2"; shift 2 ;;
    --order) ORDER_FILE="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    --repo) REPO="$2"; shift 2 ;;
    --python) PY="$2"; shift 2 ;;
    --quick) QUICK=1; shift ;;
    --clean) CLEAN=1; shift ;;
    -h|--help) sed -n 2,20p "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
if [ -z "$PY" ]; then
  if [ -x "$REPO/.venv/bin/python" ]; then PY="$REPO/.venv/bin/python"; else PY="$(command -v python3)"; fi
fi

# AGENT-8's order (docs/overnight/review-summary.md on overnight/overnight-crossreview, "Merge order (safest first)"), tips only for the stacks.
DEFAULT_ORDER=(
  overnight/overnight-ux-visual-polish
  overnight/visual-polish-3-audit-and-fix-the-views
  overnight/overnight-sec-signoff-pack
  overnight/overnight-qa-cleanroom
  overnight/overnight-ux-doctor-agents-line
  overnight/overnight-sec-workpc-profile
  overnight/overnight-rel-agent-protocol-2
  overnight/overnight-rel-data-integrity
  overnight/overnight-docs-architecture
  overnight/overnight-rel-agent-protocol-3
  overnight/overnight-install-quickstart
)
SKIP_RE='overnight/overnight-crossreview|overnight/overnight-morning-merge-kit|overnight/combined-11'   # the review, this kit, and the published combined tree itself; a branch with nothing ahead of main is skipped anyway
ORDER=()
if [ -n "$ORDER_FILE" ]; then
  while IFS= read -r line; do
    line="${line%%#*}"; line="$(echo "$line" | xargs)"
    [ -n "$line" ] && ORDER+=("$line")
  done < "$ORDER_FILE"
else
  ORDER=("${DEFAULT_ORDER[@]}")
fi

RES_DIR="${MERGE_KIT_RESOLUTIONS:-$(cd "$(dirname "$0")" && pwd)/merge-kit-resolutions}"   # <branch slug>.py, run inside the clone when that branch conflicts
TMP="$(mktemp -d "${TMPDIR:-/tmp}/merge-kit.XXXXXX")"
CLONE="$TMP/clone"
LOG="$TMP/log"
mkdir -p "$LOG"
echo "merge-kit: throwaway clone at $CLONE (the checkout at $REPO is only read)"
git clone -q --no-hardlinks "$REPO" "$CLONE" || { echo "clone failed" >&2; exit 2; }
git -C "$CLONE" config user.email "merge-kit@localhost"
git -C "$CLONE" config user.name "merge-kit (dry run)"
git -C "$CLONE" checkout -q -B trial "origin/$MAIN" 2>/dev/null || git -C "$CLONE" checkout -q -B trial "$MAIN" || { echo "no $MAIN" >&2; exit 2; }
BASE="$(git -C "$CLONE" rev-parse --short HEAD)"
echo "merge-kit: trial branch starts at $MAIN = $BASE"
# any overnight/* branch that landed after the order was written goes last, so nothing is missed (the table says it was not in the order)
LATE=()
for b in $(git -C "$CLONE" for-each-ref --format='%(refname:short)' 'refs/remotes/origin/overnight/*' | sed 's#^origin/##'); do
  case " ${ORDER[*]} " in *" $b "*) continue;; esac
  echo "$b" | grep -Eq "^($SKIP_RE)$" && continue
  [ "$(git -C "$CLONE" rev-list --count HEAD..origin/$b)" = "0" ] && continue
  LATE+=("$b")
done
if [ ${#LATE[@]} -gt 0 ]; then echo "merge-kit: not in the order, appended last: ${LATE[*]}"; ORDER+=("${LATE[@]}"); fi
# a branch rebased onto the published combined tree (overnight/combined-11) carries every other branch in its history: merged early it
# would swallow the steps after it, so it goes after every branch that is not, keeping its relative place
COMBINED="origin/overnight/combined-11"
if git -C "$CLONE" rev-parse -q --verify "$COMBINED" >/dev/null; then
  EARLY=(); ONTOP=()
  for b in "${ORDER[@]}"; do
    if git -C "$CLONE" rev-parse -q --verify "origin/$b" >/dev/null && git -C "$CLONE" merge-base --is-ancestor "$COMBINED" "origin/$b"; then ONTOP+=("$b"); else EARLY+=("$b"); fi
  done
  if [ ${#ONTOP[@]} -gt 0 ]; then echo "merge-kit: rebased onto overnight/combined-11, so merged after the rest: ${ONTOP[*]}"; ORDER=("${EARLY[@]}" "${ONTOP[@]}"); fi
fi

suggest() {   # a resolution for the conflicts the night has seen (AGENT-8's review and the authors' rebases)
  case "$1" in
    CHANGELOG.md) echo "keep both sections (the branch's first); the kit does this itself when CHANGELOG is the only conflict" ;;
    src/agentboard/doctor.py) echo "import line: take the union of the names; run(): keep both check_* calls (main's check_stop_hook and the branch's check_agents / check_watchdog), in main's order" ;;
    src/agentboard/hooks.py) echo "stop_decision: keep main's unread filter and the branch's wording; both branches add a line, neither removes one" ;;
    src/agentboard/cli.py) echo "import lines: union; a new subcommand block from each side stays; INSTRUCTIONS text: keep both paragraphs" ;;
    src/agentboard/server.py) echo "route blocks: keep both elif branches; import line: union" ;;
    docs/ARCHITECTURE.md|tests/test_docs_architecture.py) echo "module map: add the row for the module the other side added (tomlread.py, chatwake.py, statefile.py, watchdog.py)" ;;
    src/agentboard/redact.py) echo "take main's shapes and add only the branch's shim or helper (see xr-install-redact-resolve-main)" ;;
    src/agentboard/static/index.html) echo "both sides add CSS rules or functions: keep both; if the same line changed, main's wins unless the branch's card says otherwise" ;;
    *) echo "read both sides; prefer main's structure and add the branch's addition" ;;
  esac
}

resolve_changelog() {   # both sides kept, the branch's section first; returns 1 when a marker is left
  "$PY" - "$CLONE/CHANGELOG.md" <<'PYEOF'
import re, sys
p = sys.argv[1]; s = open(p).read()
pat = re.compile(r"<<<<<<< [^\n]*\n(.*?)=======\n(.*?)>>>>>>> [^\n]*\n", re.S)
s2, n = pat.subn(lambda m: m.group(2) + ("\n" if not m.group(2).endswith("\n\n") else "") + m.group(1), s)
open(p, "w").write(s2)
sys.exit(1 if "<<<<<<<" in s2 or ">>>>>>>" in s2 else 0)
PYEOF
}

page_check() {   # the page's <script> must parse (what a missing comma or a bad template literal breaks at load)
  node -e '
const fs=require("fs"); const h=fs.readFileSync(process.argv[1],"utf8"); const m=h.match(/<script>([\s\S]*)<\/script>/);
if(!m){console.log("no script block");process.exit(1)} try{new Function(m[1]);console.log("page script parses")}catch(e){console.log("PAGE SCRIPT ERROR: "+e.message);process.exit(1)}' "$CLONE/src/agentboard/static/index.html"
}

declare -a R_BRANCH R_MERGED R_TESTS R_NOTES
FAIL=0
NOMERGE=0   # a branch that did not land (conflict with no resolution, or missing): the fixups step needs every branch in
i=0
for br in "${ORDER[@]}"; do
  i=$((i+1))
  ref="origin/$br"
  if ! git -C "$CLONE" rev-parse -q --verify "$ref" >/dev/null; then
    R_BRANCH+=("$br"); R_MERGED+=("no"); R_TESTS+=("-"); R_NOTES+=("no such branch"); FAIL=1; NOMERGE=1; continue
  fi
  tip="$(git -C "$CLONE" rev-parse --short "$ref")"
  ahead="$(git -C "$CLONE" rev-list --count HEAD.."$ref")"
  echo
  echo "== $i. $br ($tip, $ahead commit(s) ahead of the trial branch)"
  if [ "$ahead" = "0" ]; then
    R_BRANCH+=("$br ($tip)"); R_MERGED+=("already"); R_TESTS+=("-"); R_NOTES+=("nothing ahead of main: drop the branch"); continue
  fi
  if git -C "$CLONE" merge -q --no-ff --no-edit "$ref" >"$LOG/$i-merge.txt" 2>&1; then
    note="clean merge"
  else
    conflicts="$(git -C "$CLONE" diff --name-only --diff-filter=U)"
    slug="$(echo "$br" | sed 's#^overnight/##')"
    fix="$RES_DIR/$slug.py"
    if [ "$conflicts" = "CHANGELOG.md" ] && resolve_changelog; then
      git -C "$CLONE" add CHANGELOG.md && git -C "$CLONE" commit -q --no-edit && note="CHANGELOG conflict, auto-resolved (both sections kept)"
    elif [ -f "$fix" ] && { echo "$conflicts" | grep -qx CHANGELOG.md && resolve_changelog; true; } && "$PY" "$fix" "$CLONE" >"$LOG/$i-resolve.txt" 2>&1 \
         && ! grep -rl "^<<<<<<< \|^>>>>>>> " $(for f in $conflicts; do echo "$CLONE/$f"; done) >/dev/null 2>&1; then
      cl="$(echo "$conflicts" | tr '\n' ' ')"; fixname="$(basename "$fix")"
      git -C "$CLONE" add -A && git -C "$CLONE" commit -q --no-edit && note="conflict in ${cl}resolved by ${fixname}, the resolution that worked tonight"
    else
      [ -f "$fix" ] && echo "   (the resolution script $fix did not clear every marker; its output is in $LOG/$i-resolve.txt)"
      echo "   CONFLICT in: $(echo "$conflicts" | tr '\n' ' ')"
      for f in $conflicts; do
        echo "   --- $f: suggested: $(suggest "$f")"
        awk '/^<<<<<<< /,/^>>>>>>> /' "$CLONE/$f" | head -60 | sed 's/^/   | /'
      done
      git -C "$CLONE" merge --abort
      cl="$(echo "$conflicts" | tr '\n' ' ')"
      R_BRANCH+=("$br ($tip)"); R_MERGED+=("no"); R_TESTS+=("-"); R_NOTES+=("conflict: ${cl}- aborted, see the suggestions above"); FAIL=1; NOMERGE=1
      continue
    fi
  fi
  pc="$(page_check 2>&1 | tail -1)"
  if [ "$QUICK" = "1" ]; then
    if "$PY" -m compileall -q "$CLONE/src/agentboard" >/dev/null 2>&1; then tests="py_compile ok; $pc"; else tests="py_compile FAILED; $pc"; FAIL=1; fi
  else
    ( cd "$CLONE" && PYTHONPATH="$CLONE/src" "$PY" -m pytest -q -p no:cacheprovider tests >"$LOG/$i-suite.txt" 2>&1 )
    tests="$(tail -1 "$LOG/$i-suite.txt" | sed 's/ in [0-9.]*s.*//')"
    case "$tests" in *failed*|*error*) FAIL=1; tests="$tests (see $LOG/$i-suite.txt)";; esac
    tests="$tests; $pc"
  fi
  case "$pc" in *ERROR*) FAIL=1;; esac
  echo "   merged: $note; $tests"
  R_BRANCH+=("$br ($tip)"); R_MERGED+=("yes"); R_TESTS+=("$tests"); R_NOTES+=("$note")
done

# cross-branch fixups: pins that are true on each branch alone and false once all are together (a doctor line count, a module map, a
# file table), applied after the last merge as one commit and tested once more; the script says what it changed.
AFTER="$RES_DIR/_after_all.py"
if [ -f "$AFTER" ] && [ "$NOMERGE" = "0" ]; then   # every branch landed: the fixups are what make the combined tree green, so a red suite above does not skip them
  echo
  echo "== after all: cross-branch fixups ($AFTER)"
  if "$PY" "$AFTER" "$CLONE" 2>&1 | sed 's/^/   /' && [ -n "$(git -C "$CLONE" status --porcelain)" ]; then
    git -C "$CLONE" add -A && git -C "$CLONE" commit -q -m "merge-kit: cross-branch fixups (the pins each branch set alone)"
    if [ "$QUICK" = "1" ]; then
      "$PY" -m compileall -q "$CLONE/src/agentboard" >/dev/null 2>&1 && tests="py_compile ok" || { tests="py_compile FAILED"; FAIL=1; }
    else
      ( cd "$CLONE" && PYTHONPATH="$CLONE/src" "$PY" -m pytest -q -p no:cacheprovider tests >"$LOG/after-all-suite.txt" 2>&1 )
      tests="$(tail -1 "$LOG/after-all-suite.txt" | sed 's/ in [0-9.]*s.*//')"
      case "$tests" in *failed*|*error*) FAIL=1; tests="$tests, see $LOG/after-all-suite.txt";; *) FAIL=0;; esac   # the final tree's suite is the verdict
    fi
    R_BRANCH+=("(cross-branch fixups)"); R_MERGED+=("yes"); R_TESTS+=("$tests; $(page_check 2>&1 | tail -1)"); R_NOTES+=("_after_all.py: the pins each branch set alone, made true for all of them")
  fi
fi

echo
echo "merge-kit result (trial branch in $CLONE, started from $MAIN = $BASE):"
printf '%-62s %-8s %-48s %s\n' "branch (tip)" "merged" "tests" "notes"
for k in "${!R_BRANCH[@]}"; do printf '%-62s %-8s %-48s %s\n' "${R_BRANCH[$k]}" "${R_MERGED[$k]}" "${R_TESTS[$k]}" "${R_NOTES[$k]}"; done
if [ -n "$OUT" ]; then
  {
    echo "| branch (tip) | merged | tests | notes |"
    echo "|---|---|---|---|"
    for k in "${!R_BRANCH[@]}"; do echo "| \`${R_BRANCH[$k]}\` | ${R_MERGED[$k]} | ${R_TESTS[$k]} | ${R_NOTES[$k]} |"; done
  } > "$OUT"
  echo "table written to $OUT"
fi
echo "final trial tip: $(git -C "$CLONE" rev-parse --short HEAD) ($(git -C "$CLONE" rev-list --count "$BASE"..HEAD) merge commits on $BASE)"
if [ "$CLEAN" = "1" ]; then rm -rf "$TMP"; echo "throwaway clone removed"; else echo "throwaway clone kept at $TMP (delete it when done)"; fi
exit $FAIL
