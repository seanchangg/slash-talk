#!/bin/bash
# Control conversation mode for the current Claude Code session.
# Usage: talkctl.sh [on|off|status|setup|toggle]
# The session ID comes from $CLAUDE_CODE_SESSION_ID, which Claude Code
# sets in the Bash tool environment.

STATE_DIR="$HOME/.claude/voice-talk"
MODE_FILE="$STATE_DIR/mode"
MODEL="$STATE_DIR/models/ggml-base.en.bin"
MODEL_URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin"
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
  SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
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
  echo "Conversation mode is ON for this session."
  echo "After this reply is spoken, the microphone opens (a tink sound marks it)."
  echo "Say \"stop listening\" or run /talk off to end it. Esc interrupts one listen."
}

off() {
  rm -f "$MODE_FILE"
  pkill -f "bin/rec" 2>/dev/null
  pkill -x say 2>/dev/null
  echo "Conversation mode is OFF."
}

status() {
  if deps_missing; then
    echo "Setup is not complete. Missing:$MISSING. Run /talk setup."
  fi
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
  toggle)
    if [ -f "$MODE_FILE" ] && [ "$(cat "$MODE_FILE")" = "$SID" ]; then off; else on; fi
    ;;
  *) echo "Unknown action: $1. Use on, off, status, setup, or no argument to toggle." ; exit 1 ;;
esac
