"""Speak instead of type, entirely on this Mac: whisper.cpp (`whisper-cli`) turns audio into text. Nothing is uploaded, no account, no download.

Used two ways: the board's mic buttons (the page records with the browser's mic and posts the clip to this machine's /api/transcribe) and
`agentboard dictate` (record in a terminal, text goes to the clipboard, optionally pasted into the window you were in).
The model is a ggml file already on the machine: [voice] model in config.toml, or $AGENTBOARD_WHISPER_MODEL, or the first of KNOWN_MODELS that exists.
Needs `whisper-cli` (brew install whisper-cpp) and `ffmpeg`."""
import base64
import binascii
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

from . import prompt as promptlib
from .store import BoardError

HOME = Path.home()
KNOWN_MODELS = [   # best speed/accuracy first; other apps' copies are only read, never changed
    HOME / "Library/Application Support/Highlight/Dependencies/Whisper/ggml-small.en.bin",
    HOME / "Library/Application Support/com.prakashjoshipax.VoiceInk/WhisperModels/ggml-large-v3-turbo-q5_0.bin",
    Path("/Applications/Rewind.app/Contents/Resources/RWTranscription_RWTranscription.bundle/Contents/Resources/Models/ggml-base.bin"),
]
VOCAB = "ORCH, AGENT-1, AGENT-2, AGENT-3, AGENT-4, agentboard, Claude, Troy, QuietDesk, BuildJamaica, pakled"   # nudges the spelling of names we use
MAX_AUDIO_BYTES = 8_000_000
MAX_SECONDS = 120
TIMEOUT_S = 90
NOISE = re.compile(r"\[(?:BLANK_AUDIO|MUSIC|NOISE|SILENCE)[^\]]*\]|\((?:music|silence|noise|blank[^)]*)\)", re.I)


def conf(board_dir):
    try:
        c = promptlib.load_config(board_dir).get("voice", {}) if board_dir else {}
    except BoardError:
        c = {}
    return c if isinstance(c, dict) else {}


def find_model(board_dir=None):
    for cand in (os.environ.get("AGENTBOARD_WHISPER_MODEL"), conf(board_dir).get("model")):
        if cand:
            p = Path(str(cand)).expanduser()
            if p.is_file():
                return p
            raise BoardError(f"voice model not found: {p}")
    for p in KNOWN_MODELS:
        if p.is_file():
            return p
    raise BoardError("no whisper model found: set [voice] model in config.toml (or AGENTBOARD_WHISPER_MODEL) to a ggml-*.bin file")


def tools():
    """(whisper-cli, ffmpeg) paths, or a BoardError saying what to install."""
    w, f = shutil.which("whisper-cli"), shutil.which("ffmpeg")
    if not w:
        raise BoardError("whisper-cli is not installed (brew install whisper-cpp)")
    if not f:
        raise BoardError("ffmpeg is not installed (brew install ffmpeg)")
    return w, f


def status(board_dir=None):
    """{'ready': bool, 'model': name or '', 'error': text}: what the board asks before it shows a mic."""
    try:
        tools()
        return {"ready": True, "model": find_model(board_dir).name, "error": ""}
    except BoardError as e:
        return {"ready": False, "model": "", "error": str(e)}


def clean(text):
    t = NOISE.sub(" ", text or "")
    return re.sub(r"\s+", " ", t).strip()


def transcribe_file(path, board_dir=None):
    """Text spoken in an audio file of any common type (webm, wav, m4a ...). Runs locally; raises BoardError when it cannot."""
    whisper, ffmpeg = tools()
    model = find_model(board_dir)
    with tempfile.TemporaryDirectory(prefix="agentboard-voice-") as d:
        wav = Path(d) / "in.wav"
        try:
            subprocess.run([ffmpeg, "-loglevel", "error", "-y", "-i", str(path), "-t", str(MAX_SECONDS), "-ar", "16000", "-ac", "1", str(wav)],
                           check=True, capture_output=True, timeout=TIMEOUT_S)
            out = subprocess.run([whisper, "-m", str(model), "-f", str(wav), "-nt", "-np", "--prompt", VOCAB],
                                 check=True, capture_output=True, text=True, timeout=TIMEOUT_S).stdout
        except subprocess.CalledProcessError as e:
            raise BoardError("could not read that audio") from e
        except subprocess.TimeoutExpired as e:
            raise BoardError("transcribing took too long") from e
    return clean(out)


def transcribe_b64(data, board_dir=None):
    """The board sends the clip as base64 inside JSON; it is written to a temp file, transcribed and deleted."""
    if not isinstance(data, str):
        raise BoardError("audio must be a base64 string")
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as e:
        raise BoardError("audio is not valid base64") from e
    if not raw:
        raise BoardError("no audio")
    if len(raw) > MAX_AUDIO_BYTES:
        raise BoardError("that clip is too long; keep it under two minutes")
    with tempfile.TemporaryDirectory(prefix="agentboard-clip-") as d:
        p = Path(d) / "clip"
        p.write_bytes(raw)
        return transcribe_file(p, board_dir)


# -- terminal dictation -----------------------------------------------------------------------------------------------------------
def record(path, device=None):
    """Start recording the microphone to `path` (16 kHz mono wav); returns the ffmpeg process. stop() ends it cleanly."""
    if sys.platform != "darwin":
        raise BoardError("agentboard dictate records with macOS's microphone; use the board's mic button elsewhere")
    _w, ffmpeg = tools()
    dev = device or os.environ.get("AGENTBOARD_MIC") or ":default"
    return subprocess.Popen([ffmpeg, "-loglevel", "error", "-y", "-f", "avfoundation", "-i", dev if dev.startswith(":") else f":{dev}",
                             "-ar", "16000", "-ac", "1", "-t", str(MAX_SECONDS), str(path)], stdin=subprocess.DEVNULL, stderr=subprocess.PIPE)


def stop(proc):
    if proc.poll() is None:
        proc.send_signal(signal.SIGINT)   # ffmpeg finishes the file on SIGINT
    try:
        _o, err = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        _o, err = proc.communicate()
    return (err or b"").decode(errors="replace")


def to_clipboard(text):
    if sys.platform == "darwin" and shutil.which("pbcopy"):
        subprocess.run(["pbcopy"], input=text.encode(), check=False)
        return True
    return False


def paste_into_front_window():
    """⌘V in whatever window has focus (needs Accessibility permission for the terminal; a refusal is reported, not hidden)."""
    r = subprocess.run(["osascript", "-e", 'tell application "System Events" to keystroke "v" using command down'], capture_output=True, text=True)
    return r.returncode == 0, r.stderr.strip()
