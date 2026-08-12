---
description: Toggle hands-free conversation mode in this session
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/talkctl.sh:*)
---

Result of `talkctl.sh $ARGUMENTS`:

!`${CLAUDE_PLUGIN_ROOT}/scripts/talkctl.sh $ARGUMENTS`

Tell the user this result in one short sentence. Do not run other tools.
If the mode is now on, your reply will be read aloud and then the microphone
opens, so end with a spoken question such as "What would you like to do?".

Usage:
- `/talk` — toggle conversation mode for this session.
- `/talk on`, `/talk off` — set it directly.
- `/talk setup` — install SoX, whisper-cpp, and the speech model.
- `/talk status` — show the state.

In conversation mode, every reply is spoken. Then the microphone opens
(after a tink sound), your words go into this same session, and the loop
repeats. "Stop listening" by voice ends the mode.
