#!/usr/bin/env python3
"""/watch entry point: download video, extract frames, parse transcript.

Prints a markdown report to stdout listing contact sheets + transcript. Claude
then Reads each sheet to see the video.

After one metadata probe the work splits into two lanes that run at the same
time: the transcript (a caption track, or audio + Whisper) and the visual side
(video + frames + sheets). One is network-bound and the other CPU-bound, so the
run takes as long as the slower lane instead of the sum of both.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))

SUMMARY_PLACEHOLDER = "<!-- RESUMEN: pendiente -->"
# Marks a temp work dir as ours, so the stale-dir sweep never touches anything
# it did not create.
WORKDIR_MARKER = ".watch-workdir"
STALE_WORKDIR_HOURS = 24

import cache as transcript_cache  # noqa: E402
import notes as note_writer  # noqa: E402
from config import frame_cap, get_config  # noqa: E402
from download import choose_caption_track, download_audio, download_video, fetch_subtitle, is_url, probe, resolve_local  # noqa: E402
from frames import MAX_FPS, auto_fps, auto_fps_focus, extract_at_timestamps, extract_keyframes, extract_scene_or_uniform, format_time, get_metadata, merge_frames, parse_time, parse_timestamps  # noqa: E402
from sheets import build_sheets, format_label  # noqa: E402
from transcribe import filter_range, format_transcript, parse_vtt  # noqa: E402
from whisper import load_api_key, transcribe_video  # noqa: E402


def sweep_stale_workdirs(max_age_hours: float = STALE_WORKDIR_HOURS) -> int:
    """Delete our own temp work dirs older than ``max_age_hours``.

    Replaces the agent's end-of-run `rm -rf`: that was one more tool round trip
    per watch, and skipping it leaked video files. Only dirs carrying our
    marker are touched.
    """
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    for candidate in Path(tempfile.gettempdir()).glob("watch-*"):
        try:
            if (candidate / WORKDIR_MARKER).exists() and candidate.stat().st_mtime < cutoff:
                shutil.rmtree(candidate, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="watch",
        description="Download a video, extract auto-scaled frames, and surface the transcript.",
    )
    ap.add_argument("source", help="Video URL or local file path")
    ap.add_argument("--max-frames", type=int, default=None, help="Override frame cap")
    ap.add_argument("--resolution", type=int, default=512, help="Frame width in pixels (default 512)")
    ap.add_argument("--fps", type=float, default=None, help="Override auto-fps")
    ap.add_argument(
        "--detail",
        choices=["transcript", "efficient", "balanced", "token-burner"],
        default=None,
        help="Fidelity/speed dial: transcript (no frames), efficient (fast keyframes, cap 50), "
             "balanced (scene, cap 100), token-burner (scene, uncapped).",
    )
    ap.add_argument(
        "--timestamps",
        type=str,
        default=None,
        help="Comma-separated absolute timestamps (SS, MM:SS, HH:MM:SS) to grab a frame at, "
             "e.g. transcript-flagged 'look here' moments. Added on top of the detail frames "
             "(reserved against the cap); with --detail transcript these become the only frames.",
    )
    ap.add_argument("--start", type=str, default=None, help="Range start (SS, MM:SS, or HH:MM:SS)")
    ap.add_argument("--end", type=str, default=None, help="Range end (SS, MM:SS, or HH:MM:SS)")
    ap.add_argument("--out-dir", type=str, default=None, help="Working directory (default: tmp)")
    ap.add_argument(
        "--lang",
        type=str,
        default=None,
        help="Caption languages to request, in preference order (e.g. 'es,en'). "
             "Overrides WATCH_SUB_LANGS.",
    )
    ap.add_argument(
        "--whisper-lang",
        type=str,
        default=None,
        help="Force the Whisper transcription language (ISO-639-1, e.g. 'es'). "
             "Default: auto-detect.",
    )
    ap.add_argument(
        "--glossary",
        type=str,
        default=None,
        help="Comma-separated domain terms fed to Whisper as a decoding prior, so "
             "names like 'Workfront' stop coming back mangled.",
    )
    ap.add_argument("--no-cache", action="store_true", help="Ignore and do not write the transcript cache")
    ap.add_argument(
        "--save",
        type=str,
        default=None,
        metavar="DIR",
        help="Write a markdown note for this video into DIR (e.g. a repo's reports/). "
             "Defaults to WATCH_NOTES_DIR when set.",
    )
    ap.add_argument("--no-index", action="store_true", help="With --save, skip updating the README index table")
    ap.add_argument(
        "--no-whisper",
        action="store_true",
        help="Disable Whisper fallback. Report frames-only if no captions available.",
    )
    ap.add_argument(
        "--whisper",
        choices=["groq", "openai"],
        default=None,
        help="Force a specific Whisper backend. Default: prefer Groq, fall back to OpenAI.",
    )
    ap.add_argument(
        "--no-sheets",
        action="store_true",
        help="List individual frames instead of tiling them into contact sheets.",
    )
    ap.add_argument(
        "--no-dedup",
        action="store_true",
        help="Disable near-duplicate frame removal. Keeps visually identical "
             "frames (static screen recordings, held slides) instead of collapsing them.",
    )
    args = ap.parse_args()

    config = get_config()
    detail = args.detail or str(config["detail"])
    sub_langs = (
        [c.strip() for c in args.lang.replace(";", ",").split(",") if c.strip()]
        if args.lang else list(config["sub_langs"])  # type: ignore[arg-type]
    )
    whisper_lang = args.whisper_lang if args.whisper_lang is not None else str(config["whisper_lang"])
    glossary = args.glossary if args.glossary is not None else str(config["glossary"])
    use_cache = bool(config["cache_enabled"]) and not args.no_cache
    save_dir = args.save or (str(config["notes_dir"]) or None)
    configured_cap = frame_cap(detail)
    if args.max_frames is not None:
        max_frames = args.max_frames
    else:
        max_frames = configured_cap
    if max_frames is not None and max_frames < 1:
        raise SystemExit("--max-frames must be greater than zero")
    budget_cap = max_frames if max_frames is not None else 100
    cue_timestamps = parse_timestamps(args.timestamps)

    if args.out_dir:
        work = Path(args.out_dir).expanduser().resolve()
    else:
        sweep_stale_workdirs()
        work = Path(tempfile.mkdtemp(prefix="watch-"))
        (work / WORKDIR_MARKER).touch()
    work.mkdir(parents=True, exist_ok=True)
    print(f"[watch] working dir: {work}", file=sys.stderr)

    cache_key = transcript_cache.cache_key(args.source, sub_langs, whisper_lang, glossary)
    cached = transcript_cache.load(cache_key) if use_cache else None
    cache_hit = cached is not None

    url_source = is_url(args.source)
    need_video = detail != "transcript" or bool(cue_timestamps)

    # Missing tools must stop the run with a pointer to the installer, not
    # degrade into "frames unavailable" (which the agent would answer around).
    required = (["yt-dlp"] if url_source else []) + ["ffmpeg", "ffprobe"]
    missing = [tool for tool in required if shutil.which(tool) is None]
    if missing:
        print(
            f"[watch] {', '.join(missing)} is not installed. "
            f"Run: python3 {SCRIPT_DIR / 'setup.py'}",
            file=sys.stderr,
        )
        return 2
    backend, api_key = (None, None) if args.no_whisper else load_api_key(args.whisper)
    whisper_ready = bool(backend and api_key)

    # One extraction for everything that follows: every yt-dlp call below
    # replays this info.json instead of re-extracting (~3-4 s each on YouTube).
    probed: dict = {"info_json": None, "raw": {}, "info": {"url": args.source}}
    track: dict | None = None
    if url_source and (need_video or not cache_hit):
        print("[watch] probing metadata and captions via yt-dlp…", file=sys.stderr)
        probed = probe(args.source, work / "download")
        if not cache_hit:
            track = choose_caption_track(probed["raw"], sub_langs)
            if track:
                print(f"[watch] caption track: {track['lang']} ({track['kind']})", file=sys.stderr)

    start_sec = parse_time(args.start)
    end_sec = parse_time(args.end)
    if start_sec is not None and start_sec < 0:
        raise SystemExit("--start must be non-negative")
    if end_sec is not None and start_sec is not None and end_sec <= start_sec:
        raise SystemExit("--end must be greater than --start")
    focused = start_sec is not None or end_sec is not None
    known_duration = float(probed["info"].get("duration") or 0) if url_source else (
        get_metadata(args.source)["duration_seconds"] if Path(args.source).expanduser().exists() else 0.0
    )
    if known_duration and start_sec is not None and start_sec >= known_duration:
        raise SystemExit(f"--start {start_sec:.1f}s is past end of video ({known_duration:.1f}s)")

    def whisper_from(media: str) -> dict:
        segments, used = transcribe_video(
            media,
            work / "audio.mp3",
            backend=backend,
            api_key=api_key,
            language=whisper_lang or None,
            prompt=glossary or None,
        )
        return {"segments": segments, "source": f"whisper ({used})", "lang": whisper_lang or "auto"}

    def transcript_lane() -> dict:
        """Captions if there is a track, else audio + Whisper. Never raises for
        an expected miss: a video without a transcript still gets frames."""
        if cache_hit:
            return {
                "segments": cached["segments"],
                "source": cached.get("transcript_source", "cached"),
                "lang": cached.get("language"),
            }
        if track:
            subtitle = fetch_subtitle(args.source, work / "download", track, probed["info_json"])
            if subtitle:
                try:
                    return {
                        "segments": parse_vtt(str(subtitle)),
                        "source": f"captions ({track['kind']})",
                        "lang": track["lang"],
                        "had_captions": True,
                    }
                except Exception as exc:
                    print(f"[watch] subtitle parse failed: {exc}", file=sys.stderr)
        if not whisper_ready:
            return {}
        try:
            if not url_source:
                if not get_metadata(args.source).get("has_audio"):
                    print("[watch] no audio stream found — proceeding without transcription", file=sys.stderr)
                    return {}
                return whisper_from(args.source)
            print("[watch] no captions — downloading audio for Whisper…", file=sys.stderr)
            audio = download_audio(args.source, work / "audio", probed["info_json"])
            if audio is None:
                # Muxed-only sites: fetch the (small) muxed file into its own
                # dir so it never races the visual lane's download.
                audio = download_video(args.source, work / "audio", info_json=probed["info_json"])
            return whisper_from(str(audio))
        except SystemExit as exc:
            print(f"[watch] whisper fallback failed: {exc}", file=sys.stderr)
            return {}

    def visual_lane() -> dict:
        if not need_video:
            return {}
        if url_source:
            print("[watch] downloading video via yt-dlp…", file=sys.stderr)
            video = str(download_video(
                args.source, work / "video", resolution=args.resolution, info_json=probed["info_json"],
            ))
        else:
            print("[watch] using local file…", file=sys.stderr)
            video = resolve_local(args.source)["video_path"]
        meta = get_metadata(video)
        duration = meta["duration_seconds"]
        if duration > 0 and start_sec is not None and start_sec >= duration:
            raise SystemExit(f"--start {start_sec:.1f}s is past end of video ({duration:.1f}s)")
        eff_start = start_sec if start_sec is not None else 0.0
        eff_end = end_sec if end_sec is not None else duration
        eff_duration = max(0.0, eff_end - eff_start)
        if focused:
            fps, target = auto_fps_focus(eff_duration, max_frames=budget_cap)
        else:
            fps, target = auto_fps(eff_duration, max_frames=budget_cap)
        if args.fps is not None:
            fps = min(args.fps, MAX_FPS)
            target = max(1, int(round(fps * eff_duration)))

        cue_frames: list[dict] = []
        cue_meta: dict = {}
        # Transcript cues are pinned: extracted first and counted against the cap
        # so the detail engine never evicts the moments the user asked for.
        if cue_timestamps:
            cue_frames, cue_meta = extract_at_timestamps(
                video, work / "frames", cue_timestamps, resolution=args.resolution,
                max_frames=max_frames, start_seconds=start_sec, end_seconds=end_sec,
            )
            if cue_meta.get("dropped_out_of_window"):
                print(
                    f"[watch] {cue_meta['dropped_out_of_window']} cue timestamp(s) outside the "
                    "focus range — dropped",
                    file=sys.stderr,
                )

        budget = max_frames if max_frames is None else max(0, max_frames - len(cue_frames))
        frames: list[dict] = []
        frame_meta: dict = {"engine": "none", "candidate_count": 0, "selected_count": 0, "fallback": False}
        if detail != "transcript" and budget != 0:
            scope = (
                f"{format_time(eff_start)}-{format_time(eff_end)} ({eff_duration:.1f}s)"
                if focused else f"full {eff_duration:.1f}s"
            )
            print(f"[watch] extracting frames over {scope} (target {target}, cap "
                  f"{'unlimited' if budget is None else budget})…", file=sys.stderr)
            if detail == "efficient":
                frames, frame_meta = extract_keyframes(
                    video, work / "frames", resolution=args.resolution, max_frames=budget,
                    start_seconds=start_sec, end_seconds=end_sec, dedup=not args.no_dedup,
                )
            else:
                frames, frame_meta = extract_scene_or_uniform(
                    video, work / "frames", fps=fps, target_frames=target,
                    resolution=args.resolution, max_frames=budget,
                    start_seconds=start_sec, end_seconds=end_sec, dedup=not args.no_dedup,
                    # token-burner opted into maximum fidelity: keep the full decode.
                    fast=detail != "token-burner", duration_seconds=eff_duration,
                )
        if cue_frames:
            frames = merge_frames(frames, cue_frames)
        sheets = [] if args.no_sheets else build_sheets(frames, work / "sheets")
        return {
            "video_path": video, "meta": meta, "duration": duration,
            "eff_start": eff_start, "eff_end": eff_end, "eff_duration": eff_duration,
            "target": target, "budget": budget, "frames": frames, "frame_meta": frame_meta,
            "cue_frames": cue_frames, "cue_meta": cue_meta, "sheets": sheets,
        }

    t0 = time.monotonic()
    visual_error: str | None = None
    with ThreadPoolExecutor(max_workers=2) as pool:
        transcript_future = pool.submit(transcript_lane)
        visual_future = pool.submit(visual_lane)
        try:
            visual = visual_future.result()
        except SystemExit as exc:
            # A failed download should not throw away a transcript we already
            # have: report what exists and say what is missing.
            visual, visual_error = {}, str(exc)
            print(f"[watch] frames unavailable: {visual_error}", file=sys.stderr)
        transcript = transcript_future.result()
    print(f"[watch] done in {time.monotonic() - t0:.1f}s", file=sys.stderr)
    if visual_error and not transcript.get("segments"):
        raise SystemExit(visual_error)

    info = dict(probed["info"])
    if cache_hit:
        for key in ("title", "uploader"):
            info[key] = info.get(key) or cached.get(key)
    if not url_source:
        info.setdefault("title", Path(args.source).name)

    meta = visual.get("meta") or {"width": None, "height": None, "codec": None, "has_audio": False}
    full_duration = (
        visual.get("duration")
        or float(info.get("duration") or 0)
        or float((cached or {}).get("duration") or 0)
    )
    if not visual and not url_source:
        full_duration = full_duration or get_metadata(args.source)["duration_seconds"]
    effective_start = visual.get("eff_start", start_sec or 0.0)
    effective_end = visual.get("eff_end", end_sec if end_sec is not None else full_duration)
    effective_duration = visual.get("eff_duration", max(0.0, effective_end - effective_start))
    target = visual.get("target", 0)
    detail_budget = visual.get("budget", max_frames)
    frames = visual.get("frames", [])
    frame_meta = visual.get("frame_meta", {"engine": "none", "candidate_count": 0, "selected_count": 0})
    cue_frames = visual.get("cue_frames", [])
    cue_meta = visual.get("cue_meta", {})
    sheets = visual.get("sheets", [])

    all_transcript_segments = list(transcript.get("segments") or [])
    transcript_source = transcript.get("source")
    transcript_lang = transcript.get("lang")
    had_captions = bool(transcript.get("had_captions"))
    transcript_segments = (
        filter_range(all_transcript_segments, start_sec, end_sec) if focused else all_transcript_segments
    )
    transcript_text = format_transcript(transcript_segments) if transcript_segments else None
    if not transcript_segments and not whisper_ready and not cache_hit:
        hint = (
            f"--whisper {args.whisper} was set but the matching API key is missing"
            if args.whisper else
            "no subtitles and no Whisper API key found"
        )
        if not args.no_whisper:
            print(
                f"[watch] {hint} — run `python3 {SCRIPT_DIR / 'setup.py'}` to enable the Whisper fallback",
                file=sys.stderr,
            )

    if use_cache and not cache_hit and all_transcript_segments:
        saved = transcript_cache.save(cache_key, {
            "source": args.source,
            "title": info.get("title"),
            "uploader": info.get("uploader"),
            "duration": full_duration,
            "transcript_source": transcript_source,
            "language": transcript_lang,
            "segments": all_transcript_segments,
        })
        if saved:
            print(f"[watch] transcript cached ({len(all_transcript_segments)} segments)", file=sys.stderr)

    print()
    print("# watch: video report")
    print()
    print(f"- **Source:** {args.source}")
    if info.get("title"):
        print(f"- **Title:** {info['title']}")
    if info.get("uploader"):
        print(f"- **Uploader:** {info['uploader']}")
    print(f"- **Duration:** {format_time(full_duration)} ({full_duration:.1f}s)")
    if focused:
        print(
            f"- **Focus range:** {format_time(effective_start)} → {format_time(effective_end)} "
            f"({effective_duration:.1f}s)"
        )
    if meta.get("width") and meta.get("height"):
        print(f"- **Resolution:** {meta['width']}x{meta['height']} ({meta.get('codec') or 'unknown codec'})")
    range_mode = "focused" if focused else "full"
    print(f"- **Detail:** {detail}")
    detail_count = frame_meta.get("selected_count", 0)
    if visual_error:
        print(f"- **Frames:** unavailable — {visual_error}. Answer from the transcript and say so.")
    elif detail != "transcript":
        cap_label = "unlimited" if detail_budget is None else str(detail_budget)
        engine = frame_meta.get("engine", "scene")
        fallback = " with uniform fallback" if frame_meta.get("engine") == "uniform" else ""
        deduped = frame_meta.get("deduped_count", 0)
        dedup_note = f", {deduped} near-duplicate{'s' if deduped != 1 else ''} dropped" if deduped else ""
        print(
            f"- **Frames:** {detail_count} selected from {frame_meta.get('candidate_count', detail_count)} "
            f"candidates ({engine}{fallback}{dedup_note}, {range_mode} range, budget {target}, cap {cap_label})"
        )
    elif not cue_frames:
        print("- **Frames:** skipped (transcript detail)")
    if cue_frames:
        dropped = cue_meta.get("dropped_out_of_window", 0)
        drop_note = f", {dropped} dropped outside range" if dropped else ""
        print(
            f"- **Cue frames:** {len(cue_frames)} at transcript-flagged timestamps "
            f"(transcript-cue{drop_note})"
        )
    if frames:
        print(f"- **Frame size:** max {args.resolution}px wide, max 1998px tall")
    if transcript_segments:
        in_range = " in range" if focused else ""
        lang_note = f", lang={transcript_lang}" if transcript_lang else ""
        cache_note = ", from cache" if cache_hit else ""
        print(
            f"- **Transcript:** {len(transcript_segments)} segments{in_range} "
            f"(via {transcript_source or 'captions'}{lang_note}{cache_note})"
        )
    else:
        print("- **Transcript:** none available")

    if detail == "token-burner" and len(frames) > 250:
        print()
        print(
            f"> **Warning:** token-burner detail selected {len(frames)} frames. "
            "This may use a large number of image tokens."
        )

    if not focused and full_duration > 600 and detail not in ("transcript", "token-burner"):
        mins = int(full_duration // 60)
        print()
        print(
            f"> **Warning:** This is a {mins}-minute video. Frame coverage is sparse at this length "
            f"under `{detail}` detail — its cap spreads thin across the full clip. For better results, "
            "re-run with `--start HH:MM:SS --end HH:MM:SS` to zoom into a section, or use "
            "`--detail token-burner` to keep every scene-change frame across the whole video."
        )

    print()
    print("## Frames")
    print()
    if sheets:
        per = len(sheets[0]["frames"])
        print(
            f"**Read every sheet below — all of them in one message, as parallel Read calls.** "
            f"Each sheet tiles up to {per} frames left→right, top→bottom, and every tile is "
            "stamped with its absolute timestamp in the source video."
        )
        print()
        for sheet in sheets:
            stamps = " · ".join(format_label(f["timestamp_seconds"]) for f in sheet["frames"])
            print(f"- `{sheet['path']}` ({sheet['grid']}): {stamps}")
        print()
        print(
            f"Each tile also exists full-size in `{work / 'frames'}` — Read one only when you "
            "need to zoom in on small text:"
        )
        print()
        print(" · ".join(
            f"{format_label(f['timestamp_seconds'])} `{Path(f['path']).name}`" for f in frames
        ))
    elif frames:
        print(
            "**Read every frame path below — all of them in one message, as parallel Read "
            "calls.** Frames are chronological; `t=MM:SS` is the absolute timestamp in the source video."
        )
        print()
        for frame in frames:
            print(
                f"- `{frame['path']}` "
                f"(t={format_time(frame['timestamp_seconds'])}, reason={frame.get('reason', 'selected')})"
            )
    else:
        print("_No frames extracted._")
    if visual.get("video_path"):
        print()
        print(f"Video file (reuse it for a `--timestamps` or `--start/--end` re-run): `{visual['video_path']}`")

    print()
    print("## Transcript")
    print()
    if transcript_text:
        label = transcript_source or "captions"
        if focused:
            print(f"_Source: {label}. Filtered to {format_time(effective_start)} → {format_time(effective_end)}:_")
        else:
            print(f"_Source: {label}._")
        print()
        print("```")
        print(transcript_text)
        print("```")
    elif detail == "transcript":
        print(
            "_No transcript available at transcript detail. Captions were missing and Whisper was "
            "unavailable or failed, so there is no visual fallback here. Re-run with "
            "`--detail balanced` for frames._"
        )
    elif focused and had_captions:
        print(f"_No transcript lines fell inside {format_time(effective_start)} → {format_time(effective_end)}._")
    else:
        setup_py = SCRIPT_DIR / "setup.py"
        print(
            "_No transcript available — proceed with frames only. "
            "Captions were missing and the Whisper fallback was unavailable "
            "(no API key set, or `--no-whisper` was used). "
            f"Run `python3 {setup_py}` to enable Whisper, then re-run._"
        )

    if save_dir:
        # The summary is written by the agent AFTER it reads the frames, which
        # is necessarily after this process exits. So the note ships with a
        # marker and the SKILL.md tells the agent to replace it via Edit.
        try:
            result = note_writer.save_note(
                save_dir,
                title=info.get("title") or Path(args.source).stem,
                source_url=info.get("url") or args.source,
                uploader=info.get("uploader"),
                duration=full_duration,
                transcript_source=transcript_source or "none",
                language=transcript_lang,
                detail=detail,
                frame_count=len(frames),
                summary=SUMMARY_PLACEHOLDER,
                transcript=transcript_text or "",
                update_index=not args.no_index,
            )
        except OSError as exc:
            print(f"[watch] note not saved: {exc}", file=sys.stderr)
        else:
            print()
            print("## Note saved")
            print()
            print(f"- **Path:** `{result['note_path']}`")
            print(f"- **README index updated:** {'yes' if result['indexed'] else 'no (no markers found)'}")
            print()
            print(
                f"**Now replace the `{SUMMARY_PLACEHOLDER}` marker in that file with your "
                "summary of the video, using the Edit tool.** Write it after you have read the "
                "frames and the transcript — it is the only part of the note this script cannot fill in."
            )

    print()
    print("---")
    print(f"_Work dir: `{work}` — temp work dirs are deleted automatically after {STALE_WORKDIR_HOURS} h._")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
