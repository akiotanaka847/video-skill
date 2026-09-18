#!/usr/bin/env python3
"""Download a video via yt-dlp, or resolve a local file path.

The flow is built around one extraction. ``probe`` asks yt-dlp for metadata and
the caption inventory once and writes an info.json; every later call (the
caption track, the video, the audio) replays it with ``--load-info-json``, so
the slow part of YouTube extraction never runs twice.

Media is fetched in the smallest form that still serves the job: video-only at
the resolution the frames actually need, and a small audio-only stream only
when there are no captions and Whisper has to run.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

SCRIPT_DIR = Path(__file__).parent.resolve()
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from config import DEFAULT_SUB_LANGS, normalize_langs, sub_lang_patterns  # noqa: E402


VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi", ".flv", ".wmv"}


def is_url(source: str) -> bool:
    if source.startswith("-"):
        return False
    parsed = urlparse(source)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def resolve_local(path: str) -> dict:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise SystemExit(f"File not found: {p}")
    if p.suffix.lower() not in VIDEO_EXTS:
        print(
            f"[watch] warning: {p.suffix} is not a known video extension, proceeding anyway",
            file=sys.stderr,
        )
    return {
        "video_path": str(p),
        "subtitle_path": None,
        "subtitle_lang": None,
        "info": {"title": p.name, "url": str(p)},
        "downloaded": False,
    }


def _pick_subtitle(out_dir: Path, markers: list[str] | None = None) -> Path | None:
    """Pick the best VTT, honouring the configured language preference order.

    `markers` comes from config.sub_lang_patterns() and is ordered: the first
    language the user listed wins over the second, and a manual track wins over
    the '-orig' auto track for the same language (markers are ordered that way).
    """
    candidates = sorted(out_dir.glob("video*.vtt"))
    if not candidates:
        return None
    if markers is None:
        _, markers = sub_lang_patterns(normalize_langs(DEFAULT_SUB_LANGS))
    for marker in markers:
        for c in candidates:
            if marker in c.name:
                return c
    return candidates[0]


def subtitle_lang(path: Path | str | None) -> str | None:
    """Extract the language tag from a yt-dlp VTT filename (video.es-419.vtt)."""
    if path is None:
        return None
    parts = Path(path).name.split(".")
    return parts[-2] if len(parts) >= 3 else None


def _pick_video(out_dir: Path) -> Path | None:
    for ext in (".mp4", ".mkv", ".webm", ".mov"):
        for candidate in out_dir.glob(f"video*{ext}"):
            return candidate
    for candidate in out_dir.glob("video.*"):
        if candidate.suffix.lower() in VIDEO_EXTS:
            return candidate
    return None


# Frames are downscaled to --resolution px wide, so anything much larger than
# that is downloaded only to be thrown away. Measured on a 55-minute webinar:
# 360p video-only is 26 MB against 104 MB for the old 720p+audio, and at 512 px
# the two are indistinguishable. Keys are the frame width; values are the
# smallest-side cap passed to yt-dlp's "res" sort (min(width, height), so a
# vertical Short is sized by its width, not its 854 px height).
DOWNLOAD_RES_STEPS = ((640, 480), (1280, 720))
DOWNLOAD_RES_MAX = 1080

# YouTube intermittently throttles single-stream downloads to ~200 KB/s; asking
# for the file in ranged 10 MB pieces sidesteps it. Harmless elsewhere.
HTTP_CHUNK = "10M"


def download_res(resolution: int) -> int:
    """Smallest-side cap for the video download, given the frame width."""
    for frame_width, cap in DOWNLOAD_RES_STEPS:
        if resolution <= frame_width:
            return cap
    return DOWNLOAD_RES_MAX


def _require_yt_dlp() -> None:
    if shutil.which("yt-dlp") is None:
        raise SystemExit("yt-dlp is not installed. Install with: brew install yt-dlp")


def _source_args(url: str, info_json: str | None) -> list[str]:
    """Replay a probe's info.json when we have one; otherwise extract afresh."""
    if info_json and Path(info_json).exists():
        return ["--load-info-json", info_json]
    return ["--no-playlist", "--", url]


def _run_with_fresh_retry(cmd_for, url: str, info_json: str | None, out_dir: Path, found) -> Path | None:
    """Run a replayed download; if it produces nothing, retry once from scratch.

    YouTube intermittently answers a replayed format URL with HTTP 403 (seen
    about one run in five while measuring). A fresh extraction signs new URLs,
    so one retry turns that into ~3 s of delay instead of a failed /watch.
    """
    subprocess.run(cmd_for(_source_args(url, info_json)), stdout=sys.stderr, stderr=sys.stderr)
    result = found()
    if result is None and info_json:
        print("[watch] replayed download failed — retrying with a fresh extraction…", file=sys.stderr)
        for partial in list(out_dir.glob("*.part")) + list(out_dir.glob("*.ytdl")):
            partial.unlink(missing_ok=True)
        subprocess.run(cmd_for(_source_args(url, None)), stdout=sys.stderr, stderr=sys.stderr)
        result = found()
    return result


def probe(url: str, out_dir: Path) -> dict:
    """Extract metadata and the caption inventory once, downloading nothing."""
    _require_yt_dlp()
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "yt-dlp",
        "--skip-download",
        "--write-info-json",
        "--no-playlist",
        "--ignore-errors",
        "-o", str(out_dir / "video.%(ext)s"),
        "--",
        url,
    ]
    subprocess.run(cmd, stdout=sys.stderr, stderr=sys.stderr)
    info_path = out_dir / "video.info.json"
    raw: dict = {}
    if info_path.exists():
        try:
            raw = json.loads(info_path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[watch] info.json parse failed: {exc}", file=sys.stderr)
    return {
        "info_json": str(info_path) if raw else None,
        "raw": raw,
        "info": _summarize_info(raw, url),
    }


def _lang_matches(key: str, code: str) -> bool:
    return key == code or key.startswith(code + "-")


def choose_caption_track(raw: dict, preferred: list[str]) -> dict | None:
    """Pick the caption track that best matches what is actually said.

    The order encodes one rule: the original beats a translation. YouTube lists
    a machine translation of its own speech recognition in 150+ languages, so a
    Spanish-first preference used to select Spanish MT for an English video —
    two lossy steps (ASR, then MT) where one would do. The agent reads the
    original language fine and translates better than that pipeline does.

    1. a manual track in a preferred language (human-written; best there is)
    2. a manual track in the video's own language
    3. the original-language speech recognition ('<lang>-orig', or the auto
       track in the declared language on extractors that don't mark it)
    4. any other manual track
    5. a machine-translated auto track in a preferred language (last resort)
    """
    manual = [k for k in (raw.get("subtitles") or {}) if k != "live_chat"]
    auto = list(raw.get("automatic_captions") or {})
    original = raw.get("language")

    for code in preferred:
        for key in manual:
            if _lang_matches(key, code):
                return {"lang": key, "auto": False, "kind": "manual"}
    if original:
        for key in manual:
            if _lang_matches(key, original):
                return {"lang": key, "auto": False, "kind": "manual"}
    for key in auto:
        if key.endswith("-orig"):
            return {"lang": key, "auto": True, "kind": "auto, original language"}
    if original and original in auto:
        return {"lang": original, "auto": True, "kind": "auto, original language"}
    if manual:
        return {"lang": manual[0], "auto": False, "kind": "manual"}
    for code in preferred:
        for key in auto:
            if _lang_matches(key, code):
                return {"lang": key, "auto": True, "kind": "auto-translated"}
    return None


def fetch_subtitle(url: str, out_dir: Path, track: dict, info_json: str | None = None) -> Path | None:
    """Download exactly one caption track as VTT.

    One track means one timedtext request instead of one per language pattern —
    YouTube answers bursts of those with HTTP 429.
    """
    _require_yt_dlp()
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "yt-dlp",
        "--skip-download",
        "--write-auto-subs" if track["auto"] else "--write-subs",
        # yt-dlp treats each entry as a regex; escape so 'es-419' is literal.
        "--sub-langs", re.escape(track["lang"]),
        "--sub-format", "vtt",
        "--convert-subs", "vtt",
        "--ignore-errors",
        "-o", str(out_dir / "video.%(ext)s"),
        *_source_args(url, info_json),
    ]
    subprocess.run(cmd, stdout=sys.stderr, stderr=sys.stderr)
    return _pick_subtitle(out_dir, [f".{track['lang']}."])


def download_video(
    url: str,
    out_dir: Path,
    resolution: int = 512,
    info_json: str | None = None,
) -> Path:
    """Fetch the video stream only, sized for the frames it will produce.

    Prefers a video-only stream (no audio to download, nothing to merge) and
    H.264, which decodes fastest. Sites that only serve muxed files fall back
    to the smallest suitable muxed format.
    """
    _require_yt_dlp()
    out_dir.mkdir(parents=True, exist_ok=True)

    def cmd_for(source: list[str]) -> list[str]:
        return [
            "yt-dlp",
            "-N", "8",
            "--http-chunk-size", HTTP_CHUNK,
            "-f", "bv/b",
            "-S", f"res:{download_res(resolution)},vcodec:h264",
            "--ignore-errors",
            "-o", str(out_dir / "video.%(ext)s"),
            *source,
        ]

    video = _run_with_fresh_retry(cmd_for, url, info_json, out_dir, lambda: _pick_video(out_dir))
    if video is None:
        raise SystemExit(f"yt-dlp did not produce a video file in {out_dir} (see its error above)")
    return video


def download_audio(url: str, out_dir: Path, info_json: str | None = None) -> Path | None:
    """Fetch a small audio-only stream for Whisper, or None if there is none.

    Whisper resamples to 16 kHz mono, so a 48 kbps stream carries everything it
    uses: 19 MB for 55 minutes against 51 MB for the "best" audio.
    """
    _require_yt_dlp()
    out_dir.mkdir(parents=True, exist_ok=True)

    def cmd_for(source: list[str]) -> list[str]:
        return [
            "yt-dlp",
            "-N", "4",
            "--http-chunk-size", HTTP_CHUNK,
            "-f", "wa[abr>=40]/ba",
            "-o", str(out_dir / "audio.%(ext)s"),
            *source,
        ]

    def found() -> Path | None:
        for candidate in sorted(out_dir.glob("audio.*")):
            if candidate.suffix not in (".json", ".part", ".ytdl"):
                return candidate
        return None

    return _run_with_fresh_retry(cmd_for, url, info_json, out_dir, found)


def _summarize_info(raw: dict, url: str) -> dict:
    if not raw:
        return {"url": url}
    return {
        "title": raw.get("title"),
        "uploader": raw.get("uploader") or raw.get("channel"),
        "duration": raw.get("duration"),
        "url": raw.get("webpage_url") or url,
    }


def download(source: str, out_dir: Path, resolution: int = 512) -> dict:
    """Resolve a local file, or fetch a URL's video (no captions, no audio)."""
    if is_url(source):
        video = download_video(source, out_dir, resolution=resolution)
        return {
            "video_path": str(video),
            "subtitle_path": None,
            "subtitle_lang": None,
            "info": {"url": source},
            "downloaded": True,
        }
    return resolve_local(source)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: download.py <url-or-path> <out-dir>", file=sys.stderr)
        raise SystemExit(2)
    result = download(sys.argv[1], Path(sys.argv[2]))
    print(json.dumps(result, indent=2))
