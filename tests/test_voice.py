"""Voice: finding the model, cleaning the text, the base64 gate, the status and the routes; whisper itself is faked."""
import base64
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentboard import voice
from agentboard.store import BoardError

from tests.test_reports import HttpTests as ReportsHttp


class Unit(unittest.TestCase):
    def test_clean_drops_whisper_noise_markers(self):
        self.assertEqual(voice.clean(" [BLANK_AUDIO] hello   there (music) "), "hello there")
        self.assertEqual(voice.clean(""), "")

    def test_model_from_env_then_config_then_known_and_a_clear_error(self):
        with tempfile.TemporaryDirectory() as d:
            m = Path(d) / "m.bin"
            m.write_bytes(b"x")
            with mock.patch.dict(os.environ, {"AGENTBOARD_WHISPER_MODEL": str(m)}):
                self.assertEqual(voice.find_model(), m)
            with mock.patch.dict(os.environ, {"AGENTBOARD_WHISPER_MODEL": str(Path(d) / "gone.bin")}):
                with self.assertRaises(BoardError):
                    voice.find_model()
            env = {k: v for k, v in os.environ.items() if k != "AGENTBOARD_WHISPER_MODEL"}
            with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(voice, "KNOWN_MODELS", [m]):
                self.assertEqual(voice.find_model(), m)
            with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(voice, "KNOWN_MODELS", [Path(d) / "none"]):
                with self.assertRaises(BoardError):
                    voice.find_model()

    def test_base64_is_checked_before_anything_runs(self):
        for bad in (None, 5, "@@@", ""):
            with self.assertRaises(BoardError):
                voice.transcribe_b64(bad)
        with mock.patch.object(voice, "MAX_AUDIO_BYTES", 3), self.assertRaises(BoardError):
            voice.transcribe_b64(base64.b64encode(b"abcd").decode())

    def test_status_says_what_is_missing(self):
        with mock.patch.object(voice.shutil, "which", return_value=None):
            s = voice.status()
        self.assertFalse(s["ready"])
        self.assertIn("whisper-cli", s["error"])


class Routes(ReportsHttp):
    """Only the voice routes run here (the inherited report tests are hidden so they do not run twice)."""

    def test_status_route_and_page_loads_the_script(self):
        with mock.patch.object(voice, "status", return_value={"ready": True, "model": "m.bin", "error": ""}):
            self.assertEqual(self.get("/api/voice")[1], b'{"ready": true, "model": "m.bin", "error": ""}')
        self.assertIn(b"AB_BASE", self.get("/voice.js")[1] + b"AB_BASE")
        self.assertIn(b"/api/transcribe", self.get("/voice.js")[1])
        self.assertIn(b'/voice.js', self.get("/")[1])

    def test_transcribe_route_runs_locally_and_bad_audio_is_a_400(self):
        with mock.patch.object(voice, "transcribe_b64", return_value="fix the login") as t:
            self.assertEqual(self.post("/api/transcribe", {"audio": "QQ=="}), {"text": "fix the login"})
            t.assert_called_once()
        import urllib.error
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.post("/api/transcribe", {"audio": "@@"})
        self.assertEqual(cm.exception.code, 400)


for _n in [n for n in dir(ReportsHttp) if n.startswith("test_")]:
    setattr(Routes, _n, None)

if __name__ == "__main__":
    unittest.main()
