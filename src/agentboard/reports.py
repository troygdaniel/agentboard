"""Card reports: when a card enters review or done, one self-contained HTML page for Troy, in .agentboard/reports/<card>-<YYYYMMDD-HHMMSS>.html.

One idea per line: the card, the one-sentence ACTION for Troy, what was built, commits, tests, files, how to try it, and Mark done / Send back.
Everything the agent wrote is escaped (the markdown renderer never passes raw HTML). Reports age out: `sweep` deletes the ones older than
[reports] keep_hours (default 24), always keeps the newest per card, and only ever touches files of this exact shape inside reports/.
Optional: the agent can add sections by writing .agentboard/reports/<card>.md (it is never swept)."""
import html
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from . import markdown as mdlib
from . import prompt as promptlib
from . import runs
from .store import BoardError

DEFAULT_KEEP_HOURS = 24.0
NAME_RE = re.compile(r"^([a-z0-9][a-z0-9-]*)-(\d{8}-\d{6})\.html$")   # <card id>-<timestamp>.html; nothing else is ever deleted
GIT_TIMEOUT_S = 10
MAX_COMMITS = 30
MAX_FILES = 60


def reports_dir(board_dir):
    return Path(board_dir) / "reports"


def conf(board_dir):
    try:
        c = promptlib.load_config(board_dir).get("reports", {})
    except BoardError:
        c = {}
    return c if isinstance(c, dict) else {}


def keep_hours(board_dir):
    try:
        v = float(conf(board_dir).get("keep_hours", DEFAULT_KEEP_HOURS))
    except (TypeError, ValueError):
        v = DEFAULT_KEEP_HOURS
    return v if v >= 0 else DEFAULT_KEEP_HOURS


def list_reports(board_dir):
    """[{file, card, at, size}], newest first."""
    out = []
    d = reports_dir(board_dir)
    for p in d.iterdir() if d.is_dir() else []:
        m = NAME_RE.match(p.name)
        if m and p.is_file():
            out.append({"file": p.name, "card": m.group(1), "at": datetime.strptime(m.group(2), "%Y%m%d-%H%M%S"), "size": p.stat().st_size})
    out.sort(key=lambda r: (r["at"], r["file"]), reverse=True)
    return out


def sweep(board_dir, hours=None, now=None):
    """Delete reports older than `hours`, except the newest report of each card. Returns the deleted file names."""
    hours = keep_hours(board_dir) if hours is None else float(hours)
    cutoff = (now or datetime.now()) - timedelta(hours=hours)
    newest = {}
    for r in list_reports(board_dir):   # newest first: the first one seen per card is the one to keep
        newest.setdefault(r["card"], r["file"])
    gone = []
    for r in list_reports(board_dir):
        if r["file"] != newest[r["card"]] and r["at"] < cutoff:
            try:
                (reports_dir(board_dir) / r["file"]).unlink()
                gone.append(r["file"])
            except OSError:
                pass
    return gone


# -- what the report says ---------------------------------------------------------------------------------------------------------
TEST_PATTERNS = (r"\b(\d+)\s+(?:tests?|specs?)\s+(?:passed|pass|ok|green)\b", r"\b(\d+)\s+passed\b",
                 r"\bRan\s+(\d+)\s+tests?\b", r"\b(\d+)\s+failed\b")


def test_totals(text):
    """Test counts the agent wrote down ('237 tests pass', 'Ran 237 tests', '12 failed'), as short phrases; [] when it said none."""
    seen, out = set(), []
    for pat in TEST_PATTERNS:
        for m in re.finditer(pat, text or "", re.I):
            phrase = m.group(0).strip()
            if phrase.lower() not in seen:
                seen.add(phrase.lower())
                out.append(phrase)
    return out[:4]


def how_to_try(body_md):
    """The markdown under a 'How to try' heading (or bold line) in the agent's body, else ''."""
    lines = (body_md or "").splitlines()
    for i, l in enumerate(lines):
        if re.match(r"^\s*(?:#{1,4}\s*|\*\*)\s*how to (?:try|test|run|use)\b", l, re.I):
            block = []
            for nxt in lines[i + 1:]:
                if re.match(r"^\s*#{1,4}\s", nxt):
                    break
                block.append(nxt)
            return "\n".join(block).strip()
    return ""


def without_sections(body_md, pattern=r"^\s*(?:#{1,4}\s*|\*\*)\s*(?:how to (?:try|test|run|use)|tests?)\b"):
    """The agent's markdown minus the sections the report shows on their own (How to try, Tests), so nothing appears twice."""
    out, skipping = [], False
    for l in (body_md or "").splitlines():
        if re.match(r"^\s*#{1,4}\s", l) or re.match(r"^\s*\*\*[^*]+\*\*\s*$", l):
            skipping = bool(re.match(pattern, l, re.I))
        if not skipping:
            out.append(l)
    return "\n".join(out).strip()


def urls_in(text):
    seen, out = set(), []
    for u in re.findall(r"https?://[^\s<>)\]\"'`]+", text or ""):
        u = u.rstrip(".,;:")
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out[:8]


def _git(args, cwd):
    try:
        p = subprocess.Popen(["git", *args], cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    except OSError:
        return None
    try:
        out, _ = p.communicate(timeout=GIT_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        p.kill()
        p.communicate()
        return None
    return out if p.returncode == 0 else None


def _remote_base(repo):
    url = (_git(["remote", "get-url", "origin"], repo) or "").strip()
    m = re.match(r"^(?:git@|https?://)(?:[^@/]+@)?([^:/]+)[:/](.+?)(?:\.git)?$", url)
    return f"https://{m.group(1)}/{m.group(2)}" if m and "github" in m.group(1) else ""


def git_info(board_dir, task, run):
    """{'repo', 'commits': [(sha, subject)], 'files': [...], 'base': remote web url or ''} for what this card changed, or {} without a repo.
    A one-shot run knows its exact branch; otherwise it is the commits made in the project's repo while the card was open."""
    c = conf(board_dir)
    wt = (run or {}).get("worktree") or {}
    repo = Path(wt["repo"]) if wt.get("repo") else Path(c["repo"]).expanduser() if c.get("repo") else Path(board_dir).resolve().parent
    if _git(["rev-parse", "--git-dir"], repo) is None:
        return {}
    if wt.get("base") and wt.get("branch"):
        rng = [f"{wt['base']}..{wt['branch']}"]
    else:
        claimed = next((e["at"] for e in task.get("log", []) if str(e.get("text", "")).startswith("Claimed by")), task.get("created", ""))
        rng = ["--all", f"--since={claimed}"]
    out = _git(["log", *rng, "--no-merges", f"--max-count={MAX_COMMITS}", "--pretty=format:%H%x09%s"], repo) or ""
    commits = [tuple(l.split("\t", 1)) for l in out.splitlines() if "\t" in l]
    files, seen = [], set()
    for sha, _s in commits:
        for f in (_git(["show", "--name-only", "--pretty=format:", sha], repo) or "").splitlines():
            if f.strip() and f not in seen:
                seen.add(f)
                files.append(f)
    return {"repo": str(repo), "commits": commits, "files": files[:MAX_FILES], "base": _remote_base(repo)}


def extras_md(board_dir, card_id):
    try:
        return (reports_dir(board_dir) / f"{card_id}.md").read_text(errors="replace")[:20000]
    except OSError:
        return ""


# -- the page -----------------------------------------------------------------------------------------------------------------------
CSS = """
:root{color-scheme:light dark;--bg:#fafaf8;--fg:#17171a;--mut:#6b6b73;--line:#e2e2de;--card:#fff;--ok:#1d7a4a;--err:#b42318;--ac:#2f6fed}
@media(prefers-color-scheme:dark){:root{--bg:#0e1116;--fg:#ececf1;--mut:#9aa0ad;--line:#262b36;--card:#151a22;--ok:#4cc38a;--err:#ff7a70;--ac:#7aa2ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{max-width:46rem;margin:0 auto;padding:24px 16px 64px}h1{font-size:24px;margin:0 0 4px;line-height:1.25}h2{font-size:13px;letter-spacing:.06em;text-transform:uppercase;color:var(--mut);margin:28px 0 8px}
.meta{color:var(--mut);font-size:14px;margin:0}.action{margin:18px 0 0;padding:14px 16px;border-radius:12px;border:1px solid var(--line);background:var(--card);border-left:6px solid var(--ok);font-size:20px;font-weight:600;line-height:1.35}
.action.ask{border-left-color:var(--err)}.action small{display:block;font-size:12px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--mut);margin-bottom:4px}
ul{padding-left:20px;margin:6px 0}li{margin:3px 0}code{font:13px ui-monospace,Menlo,monospace;background:var(--card);border:1px solid var(--line);border-radius:6px;padding:1px 5px}
a{color:var(--ac)}pre{overflow:auto;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px}details summary{cursor:pointer;min-height:32px}
.none{color:var(--mut)}.controls{position:sticky;bottom:0;background:var(--bg);border-top:1px solid var(--line);padding:12px 0;margin-top:32px;display:flex;gap:8px;flex-wrap:wrap}
button,input{font:inherit;border-radius:10px;border:1px solid var(--line);padding:10px 14px;min-height:44px;background:var(--card);color:var(--fg)}
button.go{background:var(--ok);color:#fff;border-color:var(--ok);font-weight:600}input{flex:1;min-width:12rem}#msg{width:100%;margin:0;color:var(--mut)}
"""

JS = """
const BASE = location.pathname.split('/reports/')[0];
const id = document.body.dataset.card, msg = document.getElementById('msg');
async function post(path, body) {
  const r = await fetch(BASE + path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.error || 'request failed');
  return d;
}
document.getElementById('done').onclick = async () => {
  try { await post('/api/move', { id, status: 'done' }); msg.textContent = 'Marked done.'; } catch (e) { msg.textContent = 'Could not mark done: ' + e.message; }
};
document.getElementById('back-form').onsubmit = async ev => {
  ev.preventDefault();
  const text = document.getElementById('note').value.trim();
  if (!text) { document.getElementById('note').focus(); return; }
  try { await post('/api/send-back', { id, text }); msg.textContent = 'Sent back with your note.'; document.getElementById('note').value = ''; } catch (e) { msg.textContent = 'Could not send back: ' + e.message; }
};
"""


def _li(items):
    return "<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>" if items else '<p class="none">None recorded.</p>'


def build_html(task, board_dir, run=None, git=None, extras="", now=None):
    e = html.escape
    tid, title = task["id"], task["title"]
    state = "done" if task.get("status") == "done" else "review"
    asking = bool(task.get("needs_input"))
    sentence = (task.get("question") if asking else task.get("result")) or task.get("status_text") or "Nothing was written for Troy."
    text_blob = "\n".join([task.get("result") or "", task.get("body_md") or "", *[str(x.get("text", "")) for x in task.get("log", [])]])
    built = [f"<p>{e(task.get('description') or title)}</p>"]
    if without_sections(task.get("body_md")):
        built.append(mdlib.to_html(without_sections(task["body_md"])))
    updates = [x for x in task.get("log", []) if x.get("text") and not x.get("by")][-12:]
    history = _li([f"{e(str(x.get('at', ''))[:16].replace('T', ' '))}: {e(str(x['text']))}" for x in updates])
    git = git or {}
    base = git.get("base", "")
    commits = _li([(f'<a href="{e(base)}/commit/{e(sha)}" rel="noreferrer">{e(sha[:8])}</a>' if base else f"<code>{e(sha[:8])}</code>") + f" {e(subj)}"
                   for sha, subj in git.get("commits", [])]) if git else '<p class="none">No git repository found for this board.</p>'
    files = git.get("files", [])
    tests = test_totals(text_blob)
    try_md = how_to_try(task.get("body_md") or "")
    urls = urls_in(text_blob)
    try_html = (mdlib.to_html(try_md) if try_md else "") + (_li([f'<a href="{e(u)}" rel="noreferrer">{e(u)}</a>' for u in urls]) if urls else "")
    who = e(task.get("agent") or "no agent")
    cost = ""
    if run and isinstance(run.get("cost_usd"), (int, float)):
        cost = f" · run cost ${run['cost_usd']:.2f}, {int(run.get('duration_s') or 0)}s"
    parts = [
        f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">',
        f"<title>{e(title)}: report</title><style>{CSS}</style></head><body data-card=\"{e(tid)}\"><main>",
        f'<h1>{e(title)}</h1><p class="meta"><code>{e(tid)}</code> · {who} · {state} · {e((now or datetime.now()).strftime("%d %b %Y %H:%M"))}{e(cost)}</p>',
        f'<div class="action {"ask" if asking else ""}"><small>{"Needs your answer" if asking else "For you"}</small>{e(sentence)}</div>',
        "<h2>What was built</h2>" + "".join(built),
        "<h2>What happened</h2>" + history,
        "<h2>Commits</h2>" + commits,
        "<h2>Tests</h2>" + (_li([e(t) for t in tests]) if tests else '<p class="none">The agent did not state test totals.</p>'),
        f"<h2>Files touched ({len(files)})</h2>" + (f"<details><summary>Show the list</summary>{_li([f'<code>{e(f)}</code>' for f in files])}</details>" if files else '<p class="none">None found.</p>'),
        "<h2>How to try it</h2>" + (try_html or '<p class="none">The agent did not say.</p>'),
    ]
    if extras:
        parts.append("<h2>More from the agent</h2>" + mdlib.to_html(extras))
    parts.append('<div class="controls"><button class="go" id="done" type="button">Mark done</button>'
                 '<form id="back-form" style="display:flex;gap:8px;flex:1;flex-wrap:wrap"><input id="note" maxlength="2000" placeholder="Send back with a note" aria-label="Note for the agent"><button type="submit">Send back</button></form>'
                 '<p id="msg" role="status"></p></div>')
    parts.append(f"</main><script>{JS}</script></body></html>")
    return "".join(parts)


def _latest_run(board_dir, card_id):
    rs = runs.all_runs(board_dir, card_id)
    return rs[0][1] if rs else None


def write_report(store, task_id, now=None):
    """Write the report for the card as it is now. Returns the file name."""
    now = now or datetime.now()
    task = store.get(store.load(), task_id)
    run = _latest_run(store.dir, task_id)
    page = build_html(task, store.dir, run, git_info(store.dir, task, run), extras_md(store.dir, task_id), now)
    d = reports_dir(store.dir)
    d.mkdir(parents=True, exist_ok=True)
    name = f"{task_id}-{now.strftime('%Y%m%d-%H%M%S')}.html"
    while (d / name).exists():   # two reports in one second (review then done): the second takes the next free second
        now += timedelta(seconds=1)
        name = f"{task_id}-{now.strftime('%Y%m%d-%H%M%S')}.html"
    tmp = d / f".{name}.tmp"
    tmp.write_text(page)
    tmp.replace(d / name)
    return name


def maybe_report(store, ids):
    """After a card may have entered review or done: write its report once per (state, result). Never raises: a report problem must not undo a move."""
    for tid in ids:
        try:
            t = store.get(store.load(), tid)
            if t.get("parent_id"):
                continue
            state = "done" if t["status"] == "done" else "review" if (t["status"] == "doing" and t.get("review")) else None
            if not state:
                continue
            key = f"{state}|{t.get('result') or ''}"
            if (t.get("report") or {}).get("key") == key:
                continue
            name = write_report(store, tid)
            store.set_report(tid, {"file": name, "state": state, "key": key, "at": datetime.now().isoformat(timespec="seconds")})
        except Exception:   # noqa: BLE001
            continue


def list_lines(board_dir):
    rows = []
    now = datetime.now()
    for r in list_reports(board_dir):
        age = (now - r["at"]).total_seconds() / 3600
        rows.append(f"{r['card']:<34} {age:5.1f}h  {r['size'] // 1024:>4} KB  {r['file']}")
    return rows


def index_html(board_dir, base=""):
    e = html.escape
    items = "".join(f'<li><a href="{e(base)}/reports/{e(r["file"])}">{e(r["card"])}</a> <span class="meta">{e(r["at"].strftime("%d %b %H:%M"))}</span></li>' for r in list_reports(board_dir))
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Reports</title>'
            f"<style>{CSS}</style></head><body><main><h1>Reports</h1><p class=\"meta\">Newest first. Older ones are removed after {keep_hours(board_dir):g} hours; the newest per card stays.</p>"
            + (f"<ul>{items}</ul>" if items else '<p class="none">No reports yet. One is written when a card enters review or done.</p>') + "</main></body></html>")

