#!/usr/bin/env python3
"""Kokoro speech server for the voice-talk plugin.

Kokoro takes about two seconds to load, so this server loads it once and
then waits for requests on a Unix socket. The Stop hook starts the server
when it is not running and talks to it with one JSON line per request:

  {"text": "...", "voice": "af_heart", "speed": 1.0}   speak the text
  {"stop": true}                                       stop the current speech
  {"ping": true}                                       reply "ready"

The server splits the text into sentences. It plays each sentence with
afplay while it generates the next one, so speech starts after the first
sentence is ready. It answers "done" when the speech ends, or "stopped"
when a later request cut it short. If the client closes its socket, the
speech stops too. The server exits after 30 minutes without a request.

Run it with the Python of ~/.claude/voice-talk/kokoro-venv.
"""

import json
import os
import queue
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time

HOME = os.path.expanduser("~")
STATE_DIR = os.path.join(HOME, ".claude/voice-talk")
MODEL_DIR = os.path.join(STATE_DIR, "models")
SOCK = os.path.join(STATE_DIR, "kokoro.sock")
LOG = os.path.join(STATE_DIR, "hook.log")
IDLE_EXIT = 1800
AUDIO_PREFIX = "kokoro-out-"  # /talk off kills afplay by this file name


def log(msg):
    try:
        with open(LOG, "a") as fh:
            fh.write(f"{time.strftime('%H:%M:%S')} [kokoro {os.getpid()}] {msg}\n")
    except OSError:
        pass


def sentences(text):
    """Split the text into speakable pieces of a sensible length."""
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    out = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if out and len(out[-1]) < 25:
            out[-1] = out[-1] + " " + part
        else:
            out.append(part)
    return out


class Speaker:
    """Owns the model. One worker thread does all synthesis, because the
    first Kokoro call in any new thread pays a 0.6 second setup cost."""

    def __init__(self):
        from kokoro_onnx import Kokoro
        self.kokoro = Kokoro(os.path.join(MODEL_DIR, "kokoro-v1.0.onnx"),
                             os.path.join(MODEL_DIR, "voices-v1.0.bin"))
        self.lock = threading.Lock()
        self.generation = 0
        self.player = None
        self.jobs = queue.Queue()
        self.ready = threading.Event()
        threading.Thread(target=self.work, daemon=True).start()

    def work(self):
        # The first inference is slow. Do it now, not on the first reply.
        os.unlink(self.synth("Ready.", "af_heart", 1.0))
        self.ready.set()
        while True:
            req, conn = self.jobs.get()
            try:
                result = self.speak(req.get("text", ""),
                                    req.get("voice", "af_heart"),
                                    float(req.get("speed", 1.0)), conn)
                conn.sendall(result.encode() + b"\n")
            except (OSError, ValueError) as err:
                log(f"speak failed: {err}")
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    def submit(self, req, conn):
        self.stop()
        self.jobs.put((req, conn))

    def stop(self):
        with self.lock:
            self.generation += 1
            if self.player and self.player.poll() is None:
                self.player.kill()

    def synth(self, text, voice, speed):
        import soundfile as sf
        samples, rate = self.kokoro.create(text, voice=voice, speed=speed, lang="en-us")
        fd, path = tempfile.mkstemp(prefix=AUDIO_PREFIX, suffix=".wav", dir=STATE_DIR)
        os.close(fd)
        sf.write(path, samples, rate)
        return path

    def speak(self, text, voice, speed, conn):
        """Speak the text. Return "done" or "stopped"."""
        self.stop()
        my_gen = self.generation
        pieces = sentences(text)
        if not pieces:
            return "done"
        started = time.time()
        pending = self.synth(pieces[0], voice, speed)
        log(f"first sentence ready in {time.time() - started:.1f}s "
            f"({len(pieces)} pieces)")
        for i in range(len(pieces)):
            if self.generation != my_gen or not client_alive(conn):
                os.unlink(pending)
                return "stopped"
            with self.lock:
                self.player = subprocess.Popen(
                    ["/usr/bin/afplay", pending],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                player, playing = self.player, pending
            if i + 1 < len(pieces):
                pending = self.synth(pieces[i + 1], voice, speed)
            player.wait()
            os.unlink(playing)
        return "done" if self.generation == my_gen else "stopped"


def client_alive(conn):
    """True unless the client closed its end of the socket."""
    try:
        conn.setblocking(False)
        data = conn.recv(1)
        return data != b""
    except BlockingIOError:
        return True
    except OSError:
        return False
    finally:
        try:
            conn.setblocking(True)
        except OSError:
            pass


def handle(conn, speaker, last_used):
    try:
        conn.settimeout(10)
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = conn.recv(65536)
            if not chunk:
                return
            buf += chunk
        conn.settimeout(None)
        req = json.loads(buf.decode("utf-8", errors="replace"))
        last_used[0] = time.time()
        if req.get("stop"):
            speaker.stop()
            conn.sendall(b"stopped\n")
        elif req.get("ping"):
            conn.sendall(b"ready\n")
        else:
            speaker.submit(req, conn)
            return  # the worker closes this connection
    except (OSError, ValueError) as err:
        log(f"request failed: {err}")
    try:
        conn.close()
    except OSError:
        pass


def main():
    os.makedirs(STATE_DIR, exist_ok=True)
    for name in os.listdir(STATE_DIR):
        if name.startswith(AUDIO_PREFIX):
            try:
                os.unlink(os.path.join(STATE_DIR, name))
            except OSError:
                pass
    started = time.time()
    speaker = Speaker()
    speaker.ready.wait()
    log(f"model loaded and warm in {time.time() - started:.1f}s")

    try:
        os.unlink(SOCK)
    except OSError:
        pass
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCK)
    os.chmod(SOCK, 0o600)
    server.listen(8)
    server.settimeout(60)
    last_used = [time.time()]
    while True:
        try:
            conn, _ = server.accept()
        except socket.timeout:
            if time.time() - last_used[0] > IDLE_EXIT:
                log("idle, exiting")
                break
            continue
        threading.Thread(target=handle, args=(conn, speaker, last_used),
                         daemon=True).start()
    try:
        os.unlink(SOCK)
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
