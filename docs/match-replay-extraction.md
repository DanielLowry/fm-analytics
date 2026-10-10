# Reading FM's match replays: a research brief

Status, 10 October 2026: **not started; documented for a later decision.**
The manager has approved reading this data, on the understanding that only
what FM shows on a replay may reach the app.

## Why

Some things a manager sees on FM's replays are in none of the match data the
capture reads today ([match analysis plan](match-analysis-plan.md)):

- **whether a goal came from a corner** (or a throw-in, or a free kick
  crossed in). FM's goal record has no set-piece mark: Jarra's header from a
  free kick at Welling (22 August 2020) is recorded exactly like an open-play
  cross. The app shows only a labelled guess (`analytics/match_timeline.py`,
  `CORNER_GUESS`);
- **who gave a penalty away**. The timeline names the taker only;
- **where each shot was taken from**, and every corner and free kick, not
  only the ones that led to a goal.

Each of these is visible on FM's replays, so it is fair to read. A replay is
frames of every player's and the ball's position, so each would be worked out
from the frames: a goal's clip starting with the ball at the corner flag and
play stopped, a foul in the area before a penalty, the ball's position when a
shot leaves the shooter.

## What is known

- **Replay frames are in FM's memory** for the highlights it has loaded:
  20,468 `simatch::FRAME_PLAYER_DATA` objects (0x90 bytes apart) and 4,565
  `FRAME_PERSON_DATA` on 10 October 2026, with three
  `HIGHLIGHT_INFORMATION_THREAD` objects. None is decoded.
- **The match archive does not hold them.** Each chunk of `pks_*.obs` keeps,
  after the timeline, a list of about 8 key moments (the goals and big
  chances), and nothing about corners. That list also keeps FM's private
  chance-quality value (0 to 1) for each shot, which must not be read into
  the app.
- **Saves are readable containers.** A `.fm` save (about 200 MB) starts
  `02 01 "fmf."` and is a run of zlib streams, the same container as the
  match archive the capture already reads (`02 01 "sbo."`). Getting at its
  bytes is easy; where replays sit in it, and whether every match's are kept,
  is not known.
- `Temporary/*.apm`, `*.scm` and `*.tsm` are full records of other clubs'
  matches (probably for opposition reports), not replays.

## The two routes

| | From FM's memory | From the save file |
|---|---|---|
| Covers | only highlights FM has loaded: the latest match, or one opened in FM | every match FM keeps replays for |
| Needs from the manager | opening each match's highlights in FM | nothing (the save is written when FM saves) |
| Up to date | as soon as a match is played | as of the last save or autosave |
| Main work | decode the frame objects and tie them to a match | find replays among everything else in ~1 GB of decompressed save, then decode them |

The manager rules out manual steps, which leaves the save file. Its first step
is to check whether replays are in it at all: FM's highlight-keeping setting
may keep only recent matches, or only clips rather than whole matches.

## The main issue

**Deciphering, not running it.** Once the format is understood, reading every
match's replays would take seconds to minutes, like the match archive does
now. The cost is the one-off research, and its outcome is uncertain:

1. find where the save keeps replays, if it keeps them for every match;
2. decode a frame: which bytes are each player's and the ball's position, the
   clock and the match it belongs to;
3. turn frames into football facts (a corner, a foul, where a shot was taken)
   with rules simple enough to check;
4. check those facts against matches the manager can look up, as the goal
   descriptions were (`analytics/goal_descriptions.py`).

Steps 1 and 2 are where it could fail. Expect several days of research before
knowing whether it works, with no guarantee it does.

## Rules if it goes ahead

- Read only what a replay shows: positions, the clock, who did what. Build the
  reader so FM's chance-quality value and anything else FM keeps private
  cannot pass through it, as `src/fm_analytics/bridge/visibility_result.py` does for
  attributes.
- Read files FM has already written, never while it writes them, and never
  run FM's code inside the game ([frida-discoverability](frida-discoverability.md)
  and the research rules in [tools/README.md](../tools/README.md)).
- Validate every derived fact against a handful of matches read off FM's own
  replays before showing it.
