---
name: watch
version: "1.1.0"
description: Watch a video (URL or local path). Picks the caption track in the video's own language, downloads only what the frames need, detects scenes from keyframes, and tiles frames into timestamped contact sheets so a 55-minute webinar is read in six images. Falls back to parallel Whisper with a forced language and domain glossary, caches transcripts, and can save a markdown note into a knowledge repo.
argument-hint: "<video-url-or-path> [question]"
allowed-tools: Bash, Read, Edit, AskUserQuestion
homepage: https://github.com/akiotanaka847/video-skill
repository: https://github.com/akiotanaka847/video-skill
license: MIT
user-invocable: true
---

# /watch

You don't have a video input; this skill gives you one. A Python script gets the transcript (native captions first, Whisper as fallback) while it downloads the video and extracts frames, then tiles the frames into **contact sheets** with each tile's timestamp burned in. You `Read` the sheets to see the video and combine them with the transcript to answer the user.

## Resolve `SKILL_DIR` (do this before any command)

Every `python3 ...` command below runs a bundled script under `SKILL_DIR/scripts/`. Set `SKILL_DIR` to the **absolute path of the directory containing THIS SKILL.md you just Read** — your harness told you that path in the Read result. The scripts are always a direct sibling of this file (`SKILL_DIR/scripts/watch.py`), in every install layout.

This works on every harness (Claude Code, Codex, Cursor, Gemini CLI, …) without relying on any harness-specific environment variable. Guard once at the start of a run:

```bash
SKILL_DIR="<absolute path of the directory containing the SKILL.md you Read>"
if [ ! -f "$SKILL_DIR/scripts/watch.py" ]; then
  echo "ERROR: scripts/watch.py not found under SKILL_DIR=$SKILL_DIR" >&2
  exit 1
fi
```

On **Windows**, substitute `python` for `python3` — the `python3` command there is the Microsoft Store stub and will not run the script.

## Setup — only when the script asks for it

**Do not run a preflight before watching.** Go straight to Step 1; `watch.py` checks what it needs and says so. Setup is for these cases only:

- **The script exits with `… is not installed`** → run `python3 "${SKILL_DIR}/scripts/setup.py"` (installs `yt-dlp`/`ffmpeg` on macOS, prints the command elsewhere), then re-run the same `watch.py` command.
- **The report says `no Whisper API key`** and the video had no captions → answer from the frames first, then say in one line that a Groq key would add the transcript, and offer the first-run questions below. Ask them only if the user says yes.
- **The user asks to configure `/watch`** → ask the first-run questions.

A missing Whisper key is fine: captioned videos (most of YouTube) never need it. After the questions, write `SETUP_COMPLETE=true` even if the user declined a key, so nothing asks again.

**Config inheritance:** a legacy `~/.config/watch/.env` is read as a fallback, so a Groq/OpenAI key already stored there carries over and does not need to be set up twice. We never write to that file.

### First-run questions

Ask these with `AskUserQuestion`, then write the answers into `~/.config/video-skill/.env` as bare `KEY=value` lines with **no trailing inline comment**.

1. **Whisper key** — Groq (preferred: cheaper, faster) or OpenAI. If they decline, proceed with `--no-whisper` and tell them videos without captions come back frames-only.
2. **Default detail** — present in this exact order, lightest to heaviest, keeping `(recommended)` on `balanced` even though it is not first:
   - `transcript` — no frames, transcript only.
   - `efficient` — fast keyframe pass (cap 50).
   - `balanced` (recommended) — scene-aware frames (cap 100, default).
   - `token-burner` — scene-aware, uncapped.
3. **Caption languages** — `WATCH_SUB_LANGS`, comma-separated in preference order. Default `es,en`. Free captions always beat paid Whisper, so encourage listing every language they realistically watch.

## When to use

- User pastes a video URL (YouTube, Vimeo, X, TikTok, Twitch clip, most yt-dlp-supported sites) and asks about it.
- User points at a local video file (`.mp4`, `.mov`, `.mkv`, `.webm`, …) and asks about it.
- User types `/watch <url-or-path> [question]`.

## How to invoke

**Step 1 — parse the input.** Separate the video source from the question. `/watch https://youtu.be/abc ¿en qué idioma está?` → source = `https://youtu.be/abc`, question = `¿en qué idioma está?`.

**Step 2 — run the script.** Pass the source verbatim:

```bash
python3 "${SKILL_DIR}/scripts/watch.py" "<source>"
```

**Step 3 — Read every sheet the script lists, all in one message** (parallel Read calls). Each sheet tiles up to nine frames left→right, top→bottom, and every tile shows its absolute timestamp in its top-left corner — cite those. The report also lists each tile's full-size frame; Read one only when you need to zoom in on small text. (With `--no-sheets`, or three frames or fewer, the report lists individual frames instead: read those.)

**Step 4 — answer.** You have two evidence streams: frames (what's on screen) and transcript (what's said). Cite timestamps. If the user asked nothing, summarize structure, key moments, notable visuals, spoken content.

This holds at `transcript` detail too: produce a **summary**, do not paste the raw transcript into chat. Offer it only if explicitly asked.

There is no cleanup step: temp work dirs are deleted automatically on the next run once they are a day old, so follow-ups within the day can reuse them.

## Flags

| Flag | Purpose |
|---|---|
| `--detail transcript\|efficient\|balanced\|token-burner` | Fidelity/speed dial. |
| `--start T` / `--end T` | Focus a section (`SS`, `MM:SS`, `HH:MM:SS`). Denser sampling. |
| `--timestamps T1,T2,…` | Force a frame at each timestamp. See "Transcript-cue frames". |
| `--lang es,en` | Caption languages, in preference order. Overrides `WATCH_SUB_LANGS`. |
| `--whisper-lang es` | Force the Whisper language instead of auto-detecting. |
| `--glossary "Workfront, Qaio"` | Domain terms fed to Whisper as a decoding prior. |
| `--save DIR` | Write a markdown note into DIR. See "Saving notes". |
| `--no-index` | With `--save`, skip updating the README index table. |
| `--no-cache` | Ignore and do not write the transcript cache. |
| `--max-frames N` | Override the detail-mode cap. |
| `--resolution W` | Frame width in px (default 512; 1024 only to read on-screen text). |
| `--fps F` | Override auto-fps (clamped to 2 fps). |
| `--out-dir DIR` | Keep working files somewhere specific. |
| `--whisper groq\|openai` | Force a Whisper backend. |
| `--no-whisper` | Disable the Whisper fallback entirely. |
| `--no-dedup` | Keep near-duplicate frames. |
| `--no-sheets` | List individual frames instead of contact sheets. |

## Language handling

**The track that matches what is said wins over a translation.** YouTube offers a machine translation of its own speech recognition in 150+ languages, so "Spanish first" used to mean Spanish MT for an English video — two lossy steps. The script now picks, in order: a human-written track in a preferred language (`WATCH_SUB_LANGS`, default `es,en`); a human-written track in the video's own language; the original-language speech recognition (`<lang>-orig`); any other human track; a machine translation only as a last resort. The report names the choice, e.g. `captions (auto, original language)`.

You read the original fine: answer in the user's language regardless of the transcript's.

**When Whisper is needed, two hints matter:**

- `--whisper-lang es` forces the language. Auto-detect is fine on clean monolingual speech but flips mid-file on audio that is one language carrying loanwords from another — Spanish technical content full of English product names is exactly that case.
- `--glossary "Workfront, Adobe, Qaio, OpenKAG"` is a **decoding prior, not an instruction**. Whisper conditions on it as if it were the text preceding the audio, which is what stops proper nouns coming back mangled. Pass a bare comma-separated term list; a sentence like "transcribe in Spanish" does nothing. It is re-sent for every audio chunk, so it keeps biasing long files all the way through.

Set both persistently as `WATCH_WHISPER_LANG` and `WATCH_GLOSSARY` in `~/.config/video-skill/.env`.

## Transcript cache

Transcripts are cached under `~/.cache/video-skill/transcripts/`, keyed by the source plus every input that can change the text (caption languages, forced Whisper language, glossary). Re-watching a video is then free and instant, and asking about a *different* section costs nothing extra — the cache stores the full transcript and the range filter is applied on read.

Frames are deliberately **not** cached: they depend on detail/fps/resolution/range, so the key would rarely hit, and re-extracting them is a local ffmpeg pass. A cache hit is reported in the transcript line of the report. Use `--no-cache` to bypass. Housekeeping: `python3 "${SKILL_DIR}/scripts/cache.py"` prints stats, `... cache.py purge` drops expired entries (30 days).

If the user asks a follow-up about a video you already watched **this session**, do not re-run the script at all — you already have the frames and transcript in context.

## Saving notes

`--save DIR` writes a markdown note per video: metadata table, a `## Resumen` section, and the full transcript in a collapsible block. It opens with a back-navigation link and, when the parent `README.md` contains `<!-- reports:start -->` / `<!-- reports:end -->` markers, inserts a row into that index table.

**The script cannot write the summary** — that comes from you, after you have read the frames, which is necessarily after the script exits. So the note ships with a `<!-- RESUMEN: pendiente -->` marker:

> After answering the user, **replace that marker with your summary using the Edit tool.** A note left with the marker in it is an unfinished note.

Set `WATCH_NOTES_DIR` in the config to make `--save` the default destination.

```bash
python3 "${SKILL_DIR}/scripts/watch.py" "$URL" --save ~/repo/reports
```

## Batch mode

```bash
python3 "${SKILL_DIR}/scripts/batch.py" <playlist-url|urls.txt> [--limit N] [--json]
```

This only **resolves** the work list — it does not watch anything, because seeing a video means loading frames into your context, which cannot be delegated to a subprocess. It expands a playlist with `--flat-playlist` (one request, not one per video) or reads a newline-delimited `.txt` of URLs.

Then loop yourself: **one video, one answer, one note, then the next.** Do not run several videos in a single turn — frames from multiple videos at once will blow the context budget. For long lists, confirm the count with the user before starting, and consider `--detail transcript` for a first pass.

## Recommended limits

- **Best accuracy: videos under 10 minutes.** Frame coverage scales inversely with duration.
- **Universal rate cap: 2 fps**, always.
- **Frame ceiling by detail mode:** `transcript` → none; `efficient` → 50; `balanced` → 100; `token-burner` → uncapped (soft warning past 250).
- **Full-video budget by duration:** ≤30s → ~12-30 frames; 30s-1min → ~40; 1-3min → ~60; 3-10min → ~80; >10min → up to the cap, sparsely spaced (warning printed).
- For a long video, prefer `--start`/`--end` on the relevant section over a sparse full scan. Ask the user which part they care about rather than burning tokens.

**Focused-mode budgets** (denser, still 2 fps max, still bounded by the detail cap): ≤5s → 10 frames; 5-15s → 30; 15-30s → 60; 30-60s → 80; 60-180s → 100.

## Transcript-cue frames

Visual selection misses moments a presenter flags verbally — "mira aquí", "fíjate en esto", "look at this" — because pointing at a slide is a *low* visual change. `--timestamps` forces a frame at those moments. **You** pick them, by reading the transcript:

1. Run once at any detail to get the timestamped transcript.
2. Scan for deictic cues where the speaker directs attention to the screen. This is a judgment call (ignore rhetorical "look, the point is…") — that's why it isn't a regex.
3. Re-run with `--timestamps 4:32,7:10,9:55` (absolute source times). For a URL, point the second run at the **downloaded local file** in the work dir so it doesn't re-download.

Cue frames are additive, pinned (reserved against the cap before the detail engine runs), and honor `--start/--end`. With `--detail transcript --timestamps …` they become the *only* frames.

## Failure modes

- **No transcript available** → captions missing AND (no Whisper key OR Whisper failed). Proceed frames-only and say so. If the video is not in a configured caption language, suggest re-running with `--lang <code>`.
- **Long video warning** → acknowledge it and offer a focused re-run.
- **Download fails** → the script already retries once with a fresh extraction (YouTube intermittently answers 403). If frames still fail but a transcript exists, the report says `Frames: unavailable` — answer from the transcript and say so. If nothing is available the script exits non-zero: login-required or region-locked means say so plainly; do not keep retrying.
- **Whisper fails** → error on stderr (likely invalid key or rate limit). Audio over 10 minutes is split at pauses and transcribed in parallel; partial transcripts note dropped chunks. Retry with the other backend via `--whisper openai` / `--whisper groq`.

## Token efficiency

Image tokens are billed by pixels (~width × height / 750), so a sheet costs what its tiles would cost separately — sheets save **Read calls**, not image tokens. Each Read is ~50 generated tokens before you see anything; 58 frames were ~3k generated tokens of overhead, the six sheets that replace them are ~300. A 512 px tile is ~180 tokens, so 50 frames ≈ 9k image tokens. The transcript is deduplicated and grouped into ≤10 s blocks (a 55-minute webinar is ~13k tokens). `--resolution 1024` quadruples image tokens per frame and puts two frames per sheet — use it only when the user must read on-screen text.

## Security & Permissions

**What this skill does:**
- Runs `yt-dlp` locally to fetch the video and public captions (requests go directly to the host the URL points at)
- Runs `ffmpeg` / `ffprobe` locally to extract JPEG frames and, when needed, mono 16 kHz audio
- Sends **only the extracted audio clip** to Groq (`api.groq.com`) or OpenAI (`api.openai.com`) when captions are missing and Whisper is enabled
- Writes working files to a temp dir (or `--out-dir`), transcripts to `~/.cache/video-skill/`, and notes to the `--save` directory
- Deletes its own temp work dirs once they are more than 24 h old (only dirs carrying its `.watch-workdir` marker)
- Reads/creates `~/.config/video-skill/.env` (mode `0600`); reads `~/.config/watch/.env` and a cwd `.env` as fallbacks

**What this skill does NOT do:**
- Does not upload the video itself anywhere — only extracted audio, only when needed
- Does not access any platform account (no login, no cookies, no posting)
- Does not share keys between providers, or log them to stdout, stderr, or output files
- Does not persist anything outside the paths listed above

**Bundled scripts:** `watch.py` (entry point, runs the transcript and visual lanes in parallel), `download.py` (yt-dlp, caption-track choice), `frames.py` (ffmpeg), `sheets.py` (contact sheets), `transcribe.py` (VTT parsing), `whisper.py` (Groq/OpenAI), `cache.py` (transcript cache), `notes.py` (markdown notes), `batch.py` (playlist expansion), `setup.py` (installer).

Review scripts before first use to verify behavior.
