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

`/talk setup` installs SoX and whisper-cpp with Homebrew, downloads the
Whisper base.en model (about 148 MB), and installs the Kokoro speech
engine (about 500 MB). Speech recognition and speech output both run
locally; your audio does not leave the machine.

## Use

- `/talk` — toggle conversation mode for this session.
- Speak after the tink sound. Stop speaking, and Claude answers out loud.
- Say **"stop listening"** to end the mode. `/talk off` also works.
- Esc interrupts one listen without ending the mode.

## Speech engines

`/talk setup` installs Kokoro, a free open-weights speech model that runs
on your Mac. It sounds far more natural than the macOS `say` voices, and
nothing leaves the machine. The install is about 500 MB. Kokoro needs a
Python between 3.10 and 3.14; setup installs one with Homebrew if needed.

Kokoro loads in about one second, so the plugin keeps it in a small
background server. Speech starts after the first sentence is ready, which
is well under a second, while the rest generates. The server exits after
30 minutes without a request.

| Setting | Default | Meaning |
|---|---|---|
| `CLAUDE_SPEAK_KOKORO_VOICE` | `af_heart` | Voice name. Try `af_bella`, `af_nicole`, `am_michael`, `am_adam`, `bf_emma`, `bm_george`. |
| `CLAUDE_SPEAK_KOKORO_SPEED` | `1.0` | 0.5 to 2.0 |
| `CLAUDE_SPEAK_ENGINE` | `auto` | `kokoro`, `fish`, `say`, or `personal`. `auto` takes the first one that is ready in that order. |

### Fish Audio (optional, cloud)

Fish Audio is a paid cloud engine with a $0 test tier. Only the reply
text goes to Fish Audio. Your microphone audio still stays on the machine.

1. Create an API key at https://fish.audio/app/api-keys.
2. Run `/talk key <FISH_API_KEY>`. The key is saved to
   `~/.claude/voice-talk/fish-key`. `FISH_API_KEY` in your environment
   also works.
3. Set `CLAUDE_SPEAK_ENGINE=fish`, because Kokoro wins by default.
4. Optional: pick a voice. Open any voice at https://fish.audio, copy the
   ID from the `fish.audio/m/<id>` URL, and set
   `CLAUDE_SPEAK_FISH_VOICE=<id>`.

| Setting | Default | Meaning |
|---|---|---|
| `CLAUDE_SPEAK_FISH_VOICE` | Fish Audio default voice | Voice ID |
| `CLAUDE_SPEAK_FISH_MODEL` | `s2.1-pro` | `s2.1-pro-free` costs nothing for testing |
| `CLAUDE_SPEAK_FISH_SPEED` | `1.0` | 0.5 to 2.0 |

If an engine fails, the hook writes the reason to the log and falls back
to the next one, with `say` last.

## Controls

| Action | How |
|---|---|
| Mute speech only | `touch ~/.claude/voice-talk/mute` |
| Change the `say` voice | `CLAUDE_SPEAK_VOICE=Ava` in your environment |
| Change the `say` rate | `CLAUDE_SPEAK_RATE=210` |
| Read the loop log | `~/.claude/voice-talk/hook.log` |

## Requirements

- macOS (uses the `say` and `afplay` commands)
- Homebrew
- Microphone access for your terminal (System Settings → Privacy & Security → Microphone)

## How it works

A `Stop` hook speaks the last reply with Kokoro, Fish Audio, or `say`. When conversation mode is on,
the same hook then records with SoX silence detection, transcribes with
`whisper-cli`, and returns the text as a blocked-stop reason — Claude Code
treats that as the next prompt in the same session.
