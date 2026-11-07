"""A copied config.toml must not pull any readable file into a card prompt on a locked-down machine.
markdown / file-tail providers and [prompt] template_file may read files inside the project folder; with AGENTBOARD_LOCKDOWN set, anything
that resolves outside it (an absolute path, .. , a symlink that leaves the project) is refused. Fake files only."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentboard import doctor, prompt as promptlib, providers
from agentboard.store import BoardError, Store

SECRET_LINE = "FAKE-PRIVATE-LINE-ONE"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_")}
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)
        self.proj = self.root / "proj"
        self.dir = self.proj / ".agentboard"
        self.dir.mkdir(parents=True)
        self.s = Store(self.dir)
        (self.proj / "notes.md").write_text("## Topic\nINSIDE-LINE\n")
        (self.root / "outside.md").write_text(f"## Topic\n{SECRET_LINE}\n")
        (self.proj / "link-out.md").symlink_to(self.root / "outside.md")
        (self.proj / "link-in.md").symlink_to(self.proj / "notes.md")
        (self.proj / "sub").mkdir()
        self.task = {"id": "t", "title": "T"}

    def lock(self, on=True):
        os.environ["AGENTBOARD_LOCKDOWN"] = "1" if on else "0"

    def read(self, ptype, path):
        conf = {"type": ptype, "path": str(path)}
        return providers.run_provider("k", "", conf, self.task, self.dir)


class Providers(Base):
    PATHS_OUT = lambda self: [self.root / "outside.md", "../outside.md", self.proj / "link-out.md", self.proj / "sub" / ".." / ".." / "outside.md"]

    def test_without_the_lock_nothing_changes(self):
        for ptype in ("markdown", "file-tail"):
            for path in [self.proj / "notes.md", "notes.md", *self.PATHS_OUT()]:
                self.assertTrue(self.read(ptype, path), (ptype, path))

    def test_with_the_lock_inside_the_project_is_still_read(self):
        self.lock()
        for ptype in ("markdown", "file-tail"):
            for path in (self.proj / "notes.md", "notes.md", "sub/../notes.md", self.proj / "link-in.md"):
                self.assertIn("INSIDE-LINE", self.read(ptype, path), (ptype, path))

    def test_with_the_lock_anything_that_resolves_outside_is_refused_without_a_word_of_it(self):
        self.lock()
        for ptype in ("markdown", "file-tail"):
            for path in self.PATHS_OUT():
                with self.assertRaises(providers.ProviderError) as cm:
                    self.read(ptype, path)
                self.assertNotIn(SECRET_LINE, str(cm.exception))
                self.assertIn("locked down", str(cm.exception))
                self.assertNotIn(str(self.root), str(cm.exception))      # the file name, never the folder

    def test_tilde_and_relative_escapes_are_outside_too(self):
        self.lock()
        with mock.patch.dict(os.environ, {"HOME": str(self.root)}):
            with self.assertRaises(providers.ProviderError):
                self.read("markdown", "~/outside.md")

    def test_the_lock_is_read_on_every_call(self):
        self.lock()
        with self.assertRaises(providers.ProviderError):
            self.read("markdown", self.root / "outside.md")
        self.lock(False)
        self.assertIn(SECRET_LINE, self.read("markdown", self.root / "outside.md"))

    def test_a_prompt_with_such_a_provider_still_builds_and_says_why(self):
        (self.dir / "config.toml").write_text(f'[providers.k]\ntype = "file-tail"\npath = "{self.root}/outside.md"\n')
        self.s.add("card with a file context", status="todo", task_id="c1", ctx=["k"])
        task = Store.get(self.s.load(), "c1")
        text, warnings = promptlib.build_prompt(task, self.dir)
        self.assertIn(SECRET_LINE, text)                                 # unlocked: as before
        self.lock()
        text, warnings = promptlib.build_prompt(task, self.dir)
        self.assertNotIn(SECRET_LINE, text)
        self.assertTrue(any("locked down" in w for w in warnings), warnings)


class TemplateFile(Base):
    def test_the_template_file_follows_the_same_rule(self):
        (self.proj / "tpl.txt").write_text("INSIDE-TEMPLATE {title}")
        (self.root / "out-tpl.txt").write_text(f"{SECRET_LINE} {{title}}")
        self.s.add("A card", status="todo", task_id="c1")
        task = Store.get(self.s.load(), "c1")

        def build(path):
            (self.dir / "config.toml").write_text(f'[prompt]\ntemplate_file = "{path}"\n')
            return promptlib.build_prompt(task, self.dir)[0]
        self.assertIn(SECRET_LINE, build(self.root / "out-tpl.txt"))     # unlocked
        self.lock()
        self.assertIn("INSIDE-TEMPLATE", build(self.proj / "tpl.txt"))
        for outside in (self.root / "out-tpl.txt", "../../out-tpl.txt"):
            with self.assertRaises(BoardError) as cm:
                build(outside)
            self.assertIn("locked down", str(cm.exception))
            self.assertNotIn(SECRET_LINE, str(cm.exception))


class DoctorLine(Base):
    def conf(self, text):
        (self.dir / "config.toml").write_text(text)

    def line(self, locked=None):
        return next((r for r in doctor.check_config(self.dir, locked=locked) if r[1] == "config reads"), None)

    def test_nothing_read_means_no_line(self):
        self.conf('[providers.m]\ntype = "markdown"\npath = "notes.md"\n'.replace("markdown", "command").replace('path = "notes.md"', 'run = "echo"'))
        self.assertIsNone(self.line(locked=False))

    def test_inside_the_project_is_information(self):
        self.conf('[providers.m]\ntype = "markdown"\npath = "notes.md"\n[prompt]\ntemplate_file = "tpl.txt"\n')
        r = self.line(locked=False)
        self.assertEqual(r[0], doctor.INFO)
        self.assertIn("providers.m (notes.md)", r[2])
        self.assertIn("prompt.template_file (tpl.txt)", r[2])

    def test_outside_the_project_warns_unless_the_lock_would_refuse_it(self):
        self.conf(f'[providers.k]\ntype = "file-tail"\npath = "{self.root}/outside.md"\n[providers.l]\ntype = "markdown"\npath = "link-out.md"\n')
        r = self.line(locked=False)
        self.assertEqual(r[0], doctor.WARN)
        self.assertIn("providers.k (outside.md)", r[2])
        self.assertIn("providers.l (link-out.md)", r[2])                 # a symlink that leaves the project counts as outside
        self.assertNotIn(str(self.root), r[2])                           # file names only
        r = self.line(locked=True)
        self.assertEqual(r[0], doctor.PASS)
        self.assertIn("would be refused", r[2])

    def test_the_overall_config_line_no_longer_stands_alone_as_a_clean_bill(self):
        self.conf(f'[providers.k]\ntype = "file-tail"\npath = "{self.root}/outside.md"\n')
        lines = doctor.check_config(self.dir, locked=False)
        self.assertEqual(sorted(r[0] for r in lines), [doctor.PASS, doctor.WARN])   # the switches line is clean; the reads line is not


if __name__ == "__main__":
    unittest.main()
