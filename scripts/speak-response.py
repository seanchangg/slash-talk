#!/usr/bin/env python3
"""Voice output and conversation mode for Claude Code (voice-talk plugin).

This script runs as a Stop hook on macOS. It speaks the last reply with the
`say` command.

If conversation mode is on for this session (~/.claude/voice-talk/mode holds
this session's ID), the hook then keeps the turn going:
  1. It waits until the speech is done.
  2. It plays a short cue and opens the microphone. SoX waits for your
     voice and stops after 1.5 seconds of silence.
  3. It transcribes the audio locally with whisper-cli.
  4. It returns the text to this same session as the next prompt
     (a Stop hook "block" decision), and the loop repeats.

Say "stop listening" to end the mode. /talk off also ends it.
Press Esc to interrupt a listening hook without ending the mode.
Mute the speech only: touch ~/.claude/voice-talk/mute
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HOME = os.path.expanduser("~")
STATE_DIR = os.path.join(HOME, ".claude/voice-talk")


def pick_voice():
    """Use the best installed voice: a premium one if present, else Samantha."""
    override = os.environ.get("CLAUDE_SPEAK_VOICE")
    if override and override != "personal":
        return override
    try:
        proc = subprocess.run(["/usr/bin/say", "-v", "?"],
                              capture_output=True, timeout=10)
        installed = proc.stdout.decode(errors="replace")
        for name in ("Lee (Premium)", "Lee (Enhanced)",
                     "Ava (Premium)", "Ava (Enhanced)", "Ava",
                     "Evan (Enhanced)", "Zoe (Premium)", "Allison"):
            if re.search(rf"^{re.escape(name)} +en", installed, re.MULTILINE):
                return name
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "Samantha"


VOICE = None  # resolved on first speak
RATE = os.environ.get("CLAUDE_SPEAK_RATE", "195")
MAX_CHARS = int(os.environ.get("CLAUDE_SPEAK_MAX_CHARS", "1200"))
MUTE_FILE = os.path.join(STATE_DIR, "mute")
MODE_FILE = os.path.join(STATE_DIR, "mode")
MODEL = os.path.join(STATE_DIR, "models/ggml-base.en.bin")
LOG = os.path.join(STATE_DIR, "hook.log")
SPOKEN_FILE = os.path.join(STATE_DIR, "last-spoken")
CUE = "/System/Library/Sounds/Tink.aiff"


def which(name):
    found = shutil.which(name)
    if found:
        return found
    for prefix in ("/opt/homebrew/bin", "/usr/local/bin"):
        path = os.path.join(prefix, name)
        if os.path.exists(path):
            return path
    return None


REC = which("rec")
SOX = which("sox")
WHISPER = which("whisper-cli")

STOP_PHRASES = {"stop listening", "stop listening.", "goodbye claude", "goodbye claude."}
HALLUCINATIONS = {
    "", ".", "you", "thank you.", "thanks.", "bye.", "uh", "um",
    "[silence]", "(silence)", "[blank_audio]", "[no speech]",
}


def log(msg):
    try:
        with open(LOG, "a") as fh:
            fh.write(f"{time.strftime('%H:%M:%S')} [{os.getpid()}] {msg}\n")
    except OSError:
        pass


def last_assistant_text(transcript_path):
    """Return (text, uuid, timestamp) of the last assistant message."""
    text, uid, ts = "", "", 0.0
    try:
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if entry.get("type") != "assistant":
                    continue
                if entry.get("isMeta") or entry.get("isVirtual"):
                    continue
                content = entry.get("message", {}).get("content")
                if not isinstance(content, list):
                    continue
                blocks = [
                    b.get("text", "")
                    for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                ]
                if blocks:
                    text = "\n".join(blocks)
                    uid = entry.get("uuid", "")
                    ts = parse_ts(entry.get("timestamp", ""))
    except OSError:
        return "", "", 0.0
    return text, uid, ts


def parse_ts(stamp):
    """Turn an ISO timestamp like 2026-08-12T00:26:08.219Z into epoch seconds."""
    try:
        from datetime import datetime, timezone
        dt = datetime.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S")
        return dt.replace(tzinfo=timezone.utc).timestamp()
    except (ValueError, TypeError):
        return 0.0


def fresh_assistant_text(transcript_path, session_id):
    """Return the reply that this Stop event is for, or an empty string.

    A turn can hold several text messages, and Claude Code can flush the
    final one to the transcript a moment after the Stop hook starts. So a
    message counts as current only if its timestamp is near the hook start.
    If the last message in the file is older, we wait for the flush.
    Silence is better than a stale message, so on timeout we speak nothing.
    """
    spoken = ""
    try:
        with open(SPOKEN_FILE) as fh:
            rec_session, _, rec_uuid = fh.read().strip().partition(" ")
            if rec_session == session_id:
                spoken = rec_uuid
    except OSError:
        pass

    start = time.time()
    text, uid, ts = last_assistant_text(transcript_path)
    start_uid = uid
    deadline = start + 8.0
    # Current means: written no more than 10 seconds before the hook began.
    while ts < start - 10.0 and uid == start_uid and time.time() < deadline:
        time.sleep(0.15)
        text, uid, ts = last_assistant_text(transcript_path)

    if uid != start_uid:
        log(f"reply flushed after {time.time() - start:.1f}s")
    elif ts < start - 10.0:
        log("timed out; the last transcript message is stale, staying silent")
        return ""
    if not uid or uid == spoken:
        log("last reply was already spoken, staying silent")
        return ""
    try:
        with open(SPOKEN_FILE, "w") as fh:
            fh.write(f"{session_id} {uid}")
    except OSError:
        pass
    return text


def to_speech(text):
    """Remove the markup that sounds bad when you hear it."""
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"^\s{4,}\S.*$", " ", text, flags=re.MULTILINE)
    text = re.sub(r"<[^>\n]{1,80}>", " ", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\|.*\|\s*$", " ", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*|__|~~", "", text)
    text = re.sub(r"[─-╿▀-▟]", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


PVSAY = os.path.join(STATE_DIR, "bin/pvsay")


def speak(text, wait):
    global VOICE
    subprocess.run(["/usr/bin/pkill", "-x", "say"], capture_output=True)
    subprocess.run(["/usr/bin/pkill", "-x", "pvsay"], capture_output=True)
    if not text:
        return
    # The user's Personal Voice is opt-in: set CLAUDE_SPEAK_VOICE=personal.
    if (os.environ.get("CLAUDE_SPEAK_VOICE") == "personal"
            and os.path.exists(PVSAY)):
        args = [PVSAY, "-r", RATE, text]
    else:
        if VOICE is None:
            VOICE = pick_voice()
        args = ["/usr/bin/say", "-v", VOICE, "-r", RATE, text]
    if wait:
        subprocess.run(args, capture_output=True)
    else:
        with open(os.devnull, "wb") as null:
            subprocess.Popen(args, stdout=null, stderr=null, stdin=null,
                             start_new_session=True)


def mode_is_on(session_id):
    try:
        with open(MODE_FILE) as fh:
            return fh.read().strip() == session_id
    except OSError:
        return False


def mode_off():
    try:
        os.unlink(MODE_FILE)
    except OSError:
        pass


def record(path, cue=False):
    """Record one utterance. Return True if the file has audio.

    With cue=True, play the tink only after the recorder has had time to
    open the microphone, so the first words are not clipped. macOS echo
    cancellation keeps the tink itself out of the recording.
    """
    proc = subprocess.Popen(
        [REC, "-q", "-c", "1", "-r", "16000", "-b", "16", path,
         "silence", "1", "0.1", "3%", "1", "1.5", "3%"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if cue:
        time.sleep(0.6)
        if proc.poll() is None and os.path.exists(CUE):
            subprocess.run(["/usr/bin/afplay", CUE], capture_output=True)
        log("mic open")
    try:
        _, err = proc.communicate(timeout=600)
    except subprocess.TimeoutExpired:
        proc.kill()
        log("rec hit the 10 minute cap")
        return False
    if proc.returncode != 0:
        log(f"rec exit {proc.returncode}: "
            f"{err.decode(errors='replace').strip()[:200]}")
        return False
    return os.path.exists(path) and os.path.getsize(path) > 16000  # >0.5s


def mic_ok():
    """Record half a second and check for a live signal.

    A microphone that macOS blocks records digital silence (~0.00003 peak).
    A real microphone in a quiet room still has a noise floor above that.
    """
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav = f.name
    try:
        proc = subprocess.run(
            [REC, "-q", "-c", "1", "-r", "16000", "-b", "16", wav, "trim", "0", "0.5"],
            capture_output=True, timeout=15,
        )
        if proc.returncode != 0:
            log(f"mic_ok rec failed: {proc.stderr.decode(errors='replace')[:200]}")
            return False
        stat = subprocess.run([SOX, wav, "-n", "stat"], capture_output=True)
        m = re.search(r"Maximum amplitude:\s+([\d.]+)",
                      stat.stderr.decode(errors="replace"))
        peak = float(m.group(1)) if m else 0.0
        log(f"mic_ok peak={peak}")
        return peak > 0.0003
    except subprocess.TimeoutExpired:
        log("mic_ok timed out")
        return False
    finally:
        try:
            os.unlink(wav)
        except OSError:
            pass


def transcribe(path):
    proc = subprocess.run(
        [WHISPER, "-m", MODEL, "-f", path, "--no-timestamps", "--no-prints"],
        capture_output=True,
    )
    return re.sub(r"\s+", " ", proc.stdout.decode(errors="replace")).strip()


def listen_turn(session_id):
    """Listen until we hear a real sentence. Return it, or None to stop."""
    # A test can bypass the microphone with this variable.
    fake = os.environ.get("CLAUDE_VOICE_FAKE_TEXT")
    if fake:
        return fake

    if not (REC and SOX and WHISPER and os.path.exists(MODEL)):
        mode_off()
        speak(
            "Conversation mode needs setup on this machine. "
            "Run slash talk setup, then slash talk again.",
            wait=False,
        )
        return None

    if not mic_ok():
        mode_off()
        speak(
            "I cannot hear the microphone, so I turned conversation mode off. "
            "Give your terminal microphone access in System Settings, "
            "Privacy and Security, Microphone. Then run slash talk again.",
            wait=False,
        )
        return None

    first = True
    while True:
        if not mode_is_on(session_id):
            log("mode file gone, stop listening")
            return None
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            wav = f.name
        try:
            ok = record(wav, cue=first)
            first = False
            if not ok:
                log("recording failed or too short")
                # The mic failed or /talk off killed the recorder.
                if not mode_is_on(session_id):
                    return None
                time.sleep(1)
                continue
            text = transcribe(wav)
            log(f"heard: {text!r}")
        finally:
            try:
                os.unlink(wav)
            except OSError:
                pass

        low = text.lower().strip()
        if low in HALLUCINATIONS:
            continue
        if low in STOP_PHRASES:
            mode_off()
            speak("Goodbye.", wait=False)
            return None
        return text


def main():
    if sys.platform != "darwin" or not os.path.exists("/usr/bin/say"):
        return 0
    os.makedirs(STATE_DIR, exist_ok=True)

    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0

    session_id = payload.get("session_id", "")
    transcript_path = payload.get("transcript_path")
    conversing = mode_is_on(session_id)
    log(f"stop hook: session={session_id[:8]} conversing={conversing} "
        f"stop_hook_active={payload.get('stop_hook_active')}")

    speech = ""
    if transcript_path and not os.path.exists(MUTE_FILE):
        speech = to_speech(fresh_assistant_text(transcript_path, session_id))
        if len(speech) > MAX_CHARS:
            speech = speech[:MAX_CHARS].rsplit(" ", 1)[0] + ", and more on screen."

    if not conversing:
        speak(speech, wait=False)
        return 0

    speak(speech, wait=True)
    text = listen_turn(session_id)
    if not text:
        return 0

    print(json.dumps({
        "decision": "block",
        "reason": (
            f'The user said this by voice: "{text}". Respond to it. '
            "Conversation mode is on, so your reply will be read aloud. "
            "Keep it short and speakable."
        ),
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
