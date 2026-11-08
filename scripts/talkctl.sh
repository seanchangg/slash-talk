#!/bin/bash
# Control conversation mode for the current Claude Code session.
# Usage: talkctl.sh [on|off|status|setup|toggle|key <FISH_API_KEY>]
# The session ID comes from $CLAUDE_CODE_SESSION_ID, which Claude Code
# sets in the Bash tool environment.

STATE_DIR="$HOME/.claude/voice-talk"
MODE_FILE="$STATE_DIR/mode"
KEY_FILE="$STATE_DIR/fish-key"
MODEL="$STATE_DIR/models/ggml-base.en.bin"
MODEL_URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin"
KOKORO_VENV="$STATE_DIR/kokoro-venv"
KOKORO_MODEL="$STATE_DIR/models/kokoro-v1.0.onnx"
KOKORO_VOICES="$STATE_DIR/models/voices-v1.0.bin"
KOKORO_URL="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
SID="$CLAUDE_CODE_SESSION_ID"
mkdir -p "$STATE_DIR"

find_bin() {
  command -v "$1" 2>/dev/null && return
  for p in /opt/homebrew/bin /usr/local/bin; do
    [ -x "$p/$1" ] && echo "$p/$1" && return
  done
  return 1
}

deps_missing() {
  MISSING=""
  find_bin rec >/dev/null || MISSING="$MISSING sox"
  find_bin whisper-cli >/dev/null || MISSING="$MISSING whisper-cpp"
  [ -f "$MODEL" ] || MISSING="$MISSING model"
  [ -n "$MISSING" ]
}

setup() {
  if [ "$(uname)" != "Darwin" ]; then
    echo "voice-talk only works on macOS. It needs the say command."
    exit 1
  fi
  BREW=$(find_bin brew)
  if [ -z "$BREW" ]; then
    echo "Homebrew is not installed. Install it from https://brew.sh first."
    exit 1
  fi
  find_bin rec >/dev/null || "$BREW" install sox
  find_bin whisper-cli >/dev/null || "$BREW" install whisper-cpp
  if [ ! -f "$MODEL" ]; then
    echo "Downloading the Whisper base.en model (about 148 MB)..."
    mkdir -p "$STATE_DIR/models"
    curl -sL -o "$MODEL" "$MODEL_URL" || { echo "The model download failed."; exit 1; }
  fi
  setup_kokoro
  if command -v swiftc >/dev/null 2>&1 && [ ! -x "$STATE_DIR/bin/pvsay" ]; then
    echo "Compiling the Personal Voice speaker..."
    mkdir -p "$STATE_DIR/bin"
    swiftc -O -o "$STATE_DIR/bin/pvsay" "$SCRIPT_DIR/pvsay.swift" 2>/dev/null \
      && echo "Personal Voice support is ready. Claude will use your Personal Voice if you made one." \
      || echo "The Personal Voice compile failed. Claude will use a system voice."
  fi
  echo "Setup is complete. Run /talk to start conversation mode."
  echo "Note: the first listen will ask for microphone access for your terminal."
}

# Kokoro needs Python 3.10 to 3.14: the macOS system Python is 3.9, and
# onnxruntime has no wheels for newer versions yet.
find_python() {
  for p in python3.13 python3.12 python3.14 python3.11 python3.10 \
           /opt/homebrew/bin/python3 /usr/local/bin/python3 python3; do
    P=$(find_bin "$p") || continue
    "$P" -c 'import sys; sys.exit(0 if (3, 10) <= sys.version_info < (3, 15) else 1)' 2>/dev/null \
      && echo "$P" && return
  done
  return 1
}

setup_kokoro() {
  if [ -x "$KOKORO_VENV/bin/python" ] && [ -f "$KOKORO_MODEL" ] && [ -f "$KOKORO_VOICES" ]; then
    return
  fi
  echo "Installing Kokoro, the local speech engine (about 500 MB)..."
  PY=$(find_python)
  if [ -z "$PY" ]; then
    "$BREW" install python@3.13 || { echo "Python 3.13 is needed for Kokoro. Claude will use the say command."; return; }
    PY=$(find_python) || return
  fi
  if [ ! -x "$KOKORO_VENV/bin/python" ]; then
    "$PY" -m venv "$KOKORO_VENV" || { echo "The Kokoro virtual environment failed. Claude will use the say command."; return; }
    "$KOKORO_VENV/bin/pip" install -q --upgrade pip
    "$KOKORO_VENV/bin/pip" install -q kokoro-onnx soundfile \
      || { echo "The Kokoro install failed. Claude will use the say command."; rm -rf "$KOKORO_VENV"; return; }
  fi
  mkdir -p "$STATE_DIR/models"
  for f in kokoro-v1.0.onnx voices-v1.0.bin; do
    [ -f "$STATE_DIR/models/$f" ] && continue
    echo "Downloading $f..."
    curl -sL -o "$STATE_DIR/models/$f" "$KOKORO_URL/$f" \
      || { echo "The Kokoro model download failed. Claude will use the say command."; rm -f "$STATE_DIR/models/$f"; return; }
  done
  echo "Kokoro is ready. Claude speaks with the af_heart voice."
}

kokoro_ready() {
  [ -x "$KOKORO_VENV/bin/python" ] && [ -f "$KOKORO_MODEL" ] && [ -f "$KOKORO_VOICES" ]
}

# Start the Kokoro server now so the first reply does not wait for the model.
kokoro_warm() {
  kokoro_ready || return
  [ -S "$STATE_DIR/kokoro.sock" ] && return
  nohup "$KOKORO_VENV/bin/python" -I "$SCRIPT_DIR/kokoro-server.py" >/dev/null 2>&1 &
}

kokoro_stop() {
  pkill -f "voice-talk/kokoro-out-" 2>/dev/null
  [ -S "$STATE_DIR/kokoro.sock" ] || return
  /usr/bin/python3 - "$STATE_DIR/kokoro.sock" <<'PY' 2>/dev/null
import socket, sys
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.settimeout(2)
try:
    s.connect(sys.argv[1]); s.sendall(b'{"stop": true}\n'); s.recv(64)
except OSError:
    pass
PY
}

on() {
  if [ -z "$SID" ]; then
    echo "No session ID found. Run this from inside a Claude Code session."
    exit 1
  fi
  if deps_missing; then
    echo "Missing:$MISSING. Run /talk setup first."
    exit 1
  fi
  echo "$SID" > "$MODE_FILE"
  kokoro_warm
  echo "Conversation mode is ON for this session."
  echo "After this reply is spoken, the microphone opens (a tink sound marks it)."
  echo "Say \"stop listening\" or run /talk off to end it. Esc interrupts one listen."
}

off() {
  rm -f "$MODE_FILE"
  pkill -f "bin/rec" 2>/dev/null
  pkill -x say 2>/dev/null
  pkill -f "voice-talk/speech.mp3" 2>/dev/null
  kokoro_stop
  echo "Conversation mode is OFF."
}

key() {
  if [ -z "$1" ]; then
    echo "Usage: /talk key <FISH_API_KEY>. Get a key at https://fish.audio/app/api-keys"
    exit 1
  fi
  (umask 077; printf '%s\n' "$1" > "$KEY_FILE")
  echo "The Fish Audio key is saved. Set CLAUDE_SPEAK_ENGINE=fish to prefer it over Kokoro."
  echo "Pick a voice with CLAUDE_SPEAK_FISH_VOICE=<id> from a fish.audio/m/<id> page."
}

tts_status() {
  ENGINE="${CLAUDE_SPEAK_ENGINE:-auto}"
  HAS_KEY=""
  { [ -n "$FISH_API_KEY" ] || [ -n "$FISH_AUDIO_API_KEY" ] || [ -s "$KEY_FILE" ]; } && HAS_KEY=1
  if [ "$ENGINE" = auto ]; then
    if kokoro_ready; then ENGINE=kokoro; elif [ -n "$HAS_KEY" ]; then ENGINE=fish; else ENGINE=say; fi
  fi
  case "$ENGINE" in
    kokoro) echo "Speech: Kokoro, local (voice ${CLAUDE_SPEAK_KOKORO_VOICE:-af_heart})." ;;
    fish) echo "Speech: Fish Audio (${CLAUDE_SPEAK_FISH_MODEL:-s2.1-pro}${CLAUDE_SPEAK_FISH_VOICE:+, voice $CLAUDE_SPEAK_FISH_VOICE})." ;;
    personal) echo "Speech: your macOS Personal Voice." ;;
    *) echo "Speech: macOS say. Run /talk setup to install Kokoro, a better local voice." ;;
  esac
}

status() {
  if deps_missing; then
    echo "Setup is not complete. Missing:$MISSING. Run /talk setup."
  fi
  tts_status
  if [ -f "$MODE_FILE" ]; then
    CUR=$(cat "$MODE_FILE")
    if [ "$CUR" = "$SID" ]; then
      echo "Conversation mode is ON for this session."
    else
      echo "Conversation mode is ON for another session ($CUR)."
    fi
  else
    echo "Conversation mode is OFF."
  fi
}

case "${1:-toggle}" in
  on|start) on ;;
  off|stop|end) off ;;
  status) status ;;
  setup) setup ;;
  key) key "$2" ;;
  toggle)
    if [ -f "$MODE_FILE" ] && [ "$(cat "$MODE_FILE")" = "$SID" ]; then off; else on; fi
    ;;
  *) echo "Unknown action: $1. Use on, off, status, setup, key, or no argument to toggle." ; exit 1 ;;
esac
