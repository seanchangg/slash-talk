# voice-talk

Hands-free conversation mode for Claude Code on macOS. Built so I could micromanage my UI as I was cooking dinner.

`/talk` turns the current session into a voice conversation. Claude speaks
each reply. Then the microphone opens, your words become the next prompt in
the same session, and the loop repeats. You do not touch the keyboard.

## Install

```
/plugin marketplace add seanchangg/slash-talk
/plugin install voice-talk@seanchang-plugins
/talk setup
```

`/talk setup` installs SoX and whisper-cpp with Homebrew and downloads the
Whisper base.en model (about 148 MB). Speech recognition runs locally; your
audio does not leave the machine.

## Use

- `/talk` — toggle conversation mode for this session.
- Speak after the tink sound. Stop speaking, and Claude answers out loud.
- Say **"stop listening"** to end the mode. `/talk off` also works.
- Esc interrupts one listen without ending the mode.

## Controls

| Action | How |
|---|---|
| Mute speech only | `touch ~/.claude/voice-talk/mute` |
| Change the voice | `CLAUDE_SPEAK_VOICE=Ava` in your environment |
| Change the rate | `CLAUDE_SPEAK_RATE=210` |
| Read the loop log | `~/.claude/voice-talk/hook.log` |

## Requirements

- macOS (uses the `say` command)
- Homebrew
- Microphone access for your terminal (System Settings → Privacy & Security → Microphone)

## How it works

A `Stop` hook speaks the last reply with `say`. When conversation mode is on,
the same hook then records with SoX silence detection, transcribes with
`whisper-cli`, and returns the text as a blocked-stop reason — Claude Code
treats that as the next prompt in the same session.
