#!/usr/bin/env python3
"""Parse a WebVTT subtitle file into a clean, timestamped transcript.

YouTube auto-subs emit *rolling* cues: every cue repeats the previous line and
then adds a new one, so a naive parse carries each sentence twice. We strip the
carried-over words (see _new_words) and keep only what each cue adds.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


TS_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[.,](\d{3})\s+-->\s+(\d{2}):(\d{2}):(\d{2})[.,](\d{3})"
)
TAG_RE = re.compile(r"<[^>]+>")


def _to_seconds(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def parse_vtt(path: str) -> list[dict]:
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()

    segments: list[dict] = []
    i = 0
    while i < len(lines):
        match = TS_RE.match(lines[i])
        if not match:
            i += 1
            continue

        start = _to_seconds(*match.groups()[:4])
        end = _to_seconds(*match.groups()[4:])
        i += 1

        cue_lines: list[str] = []
        # Only a truly empty line ends a cue (WebVTT). YouTube opens cues with a
        # lone " " placeholder; stopping there dropped the cue's new line and
        # left it to the next transition cue, stamped ~3 s late.
        while i < len(lines) and lines[i] != "" and not TS_RE.match(lines[i]):
            cleaned = TAG_RE.sub("", lines[i]).strip()
            if cleaned:
                cue_lines.append(cleaned)
            i += 1

        cue_text = " ".join(cue_lines).strip()
        if cue_text:
            segments.append({"start": round(start, 2), "end": round(end, 2), "text": cue_text})
        i += 1

    return _dedupe(segments)


# A carried-over run must be at least this many words before we strip it. A
# single shared word between two cues ("...said no" / "no, I mean...") is far
# more likely a real repetition in manual subtitles than a rolling carry-over,
# which on YouTube is always a whole caption line.
MIN_CARRY_WORDS = 2
# How far back to look for the carried-over run. A rolling cue repeats one
# caption line (~5-15 words), so this comfortably covers it without making the
# overlap search quadratic on long transcripts.
CARRY_LOOKBACK = 40


def _new_words(tail: list[str], words: list[str]) -> list[str]:
    """Return the words of a cue that were not already emitted.

    Finds the longest run where the cue's opening words equal the end of what
    has been emitted so far, and drops it. A cue that is *entirely* a repeat
    (YouTube's 10 ms transition cues) comes back empty.
    """
    longest = min(len(tail), len(words))
    for k in range(longest, 0, -1):
        if tail[-k:] == words[:k]:
            if k == len(words) or k >= MIN_CARRY_WORDS:
                return words[k:]
            break
    return words


def _dedupe(segments: list[dict]) -> list[dict]:
    """Collapse rolling duplicates common in YouTube auto-subs.

    Works on words rather than whole cue strings: the rolling format repeats
    the *previous line*, not the previous cue, so a cue never equals or extends
    the accumulated segment once two lines have gone by. Manual subtitles have
    no carry-over, so they pass through unchanged.
    """
    out: list[dict] = []
    tail: list[str] = []
    for seg in segments:
        words = seg["text"].split()
        fresh = _new_words(tail, words)
        if not fresh:
            if out:
                out[-1]["end"] = max(out[-1]["end"], seg["end"])
            continue
        out.append({"start": seg["start"], "end": seg["end"], "text": " ".join(fresh)})
        tail = (tail + fresh)[-CARRY_LOOKBACK:]
    return out


def filter_range(
    segments: list[dict],
    start_seconds: float | None,
    end_seconds: float | None,
) -> list[dict]:
    """Return segments whose time range overlaps [start, end]."""
    if start_seconds is None and end_seconds is None:
        return segments
    lo = start_seconds if start_seconds is not None else float("-inf")
    hi = end_seconds if end_seconds is not None else float("inf")
    return [seg for seg in segments if seg["end"] >= lo and seg["start"] <= hi]


# Consecutive lines are merged into blocks of at most this many seconds, with
# one timestamp per block. Deduped caption lines are ~7 words, so a per-line
# "[MM:SS] " stamp was ~40% of the transcript's tokens. 10 s is the knee: 20 s
# blocks save little more, and the --timestamps cue workflow needs to point at
# a moment, not a paragraph.
BLOCK_SECONDS = 10.0
# A pause longer than this starts a new block even if the block is short, so a
# stamp never sits on top of a silence and drifts from the words it labels.
BLOCK_BREAK_GAP = 3.0


def _stamp(seconds: float) -> str:
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    if hours:
        return f"[{hours}:{rem // 60:02d}:{rem % 60:02d}]"
    return f"[{rem // 60:02d}:{rem % 60:02d}]"


def group_blocks(segments: list[dict], block_seconds: float = BLOCK_SECONDS) -> list[dict]:
    """Merge consecutive segments into blocks spanning at most ``block_seconds``."""
    blocks: list[dict] = []
    for seg in segments:
        last = blocks[-1] if blocks else None
        if (
            last is not None
            and seg["start"] - last["start"] < block_seconds
            and seg["start"] - last["end"] <= BLOCK_BREAK_GAP
        ):
            last["text"] = f"{last['text']} {seg['text']}"
            last["end"] = max(last["end"], seg["end"])
            continue
        blocks.append({"start": seg["start"], "end": seg["end"], "text": seg["text"]})
    return blocks


def format_transcript(segments: list[dict], block_seconds: float = BLOCK_SECONDS) -> str:
    return "\n".join(
        f"{_stamp(block['start'])} {block['text']}"
        for block in group_blocks(segments, block_seconds)
    )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: transcribe.py <vtt-path>", file=sys.stderr)
        raise SystemExit(2)
    print(format_transcript(parse_vtt(sys.argv[1])))
