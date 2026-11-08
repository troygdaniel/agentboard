# docs/overnight

The night of Nov 7-8 (the overnight quality push): one evidence file per card (`<card-id>.md`, screenshots beside it), AGENT-8's
cross-review (`review-summary.md`, on `overnight/overnight-crossreview`), and the merge kit.

## The merge kit

`merge-kit.sh` is a dry run of the morning merge. It clones the repo into a temp folder (the checkout it runs from is only read; no
worktree, no board, no push), starts a trial branch at `main`, and merges the `overnight/*` branches in AGENT-8's recommended order.
A conflict in `CHANGELOG.md` alone is resolved by the kit (both sections kept, the branch's first). Any other conflict is resolved by
`merge-kit-resolutions/<branch slug>.py` when that file exists (the resolution that worked in the night's dry run, a few literal lines
each, see `_lib.py`); without one the kit prints the files, the hunks and a suggestion, aborts that one merge and goes on. After each
merge that lands it checks that the page's script parses and runs the full suite (`--quick` skips the suites), and it ends with one
table: branch, merged, tests, notes. `merge-kit-dry-run.md` is that table from the night, with the conflicts and what resolved them.

    docs/overnight/merge-kit.sh --repo ~/dev/agentboard                                    # about an hour: a suite per merge
    docs/overnight/merge-kit.sh --repo ~/dev/agentboard --quick                            # minutes: merges and page check only
    docs/overnight/merge-kit.sh --order my-order.txt --out docs/overnight/merge-kit-dry-run.md --clean

The real merge in the morning is the same sequence on the live checkout, by hand or by running the kit's steps there; the resolution
scripts take the path of any checkout as their one argument.
