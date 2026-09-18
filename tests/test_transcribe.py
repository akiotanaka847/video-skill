"""VTT parsing: YouTube rolling-caption dedup and timestamp blocks."""
from __future__ import annotations

from pathlib import Path

import transcribe

# The real shape of a YouTube auto-caption VTT: each cue repeats the previous
# line, then adds a new one with inline word timings; a 10 ms transition cue
# repeats only the finished line.
ROLLING = """WEBVTT
Kind: captions
Language: en

00:04:10.879 --> 00:04:13.670 align:start position:0%
 
hi<00:04:11.239><c> everyone</c><00:04:12.239><c> welcome</c><00:04:12.560><c> to</c><00:04:12.920><c> experience</c><00:04:13.360><c> League</c>

00:04:13.670 --> 00:04:13.680 align:start position:0%
hi everyone welcome to experience League
 

00:04:13.680 --> 00:04:15.789 align:start position:0%
hi everyone welcome to experience League
live<00:04:14.280><c> my</c><00:04:14.439><c> name</c><00:04:14.599><c> is</c><00:04:14.799><c> Betsy</c>

00:04:15.789 --> 00:04:15.799 align:start position:0%
live my name is Betsy
 

00:04:15.799 --> 00:04:18.000 align:start position:0%
live my name is Betsy
for<00:04:16.000><c> today</c><00:04:16.500><c> it's</c><00:04:17.000><c> my</c><00:04:17.500><c> first</c><00:04:17.800><c> time</c>
"""

MANUAL = """WEBVTT

00:00:01.000 --> 00:00:03.000
Hola, ¿cómo estás?

00:00:03.500 --> 00:00:05.000
Bien, bien. ¿Y tú?

00:00:05.500 --> 00:00:07.000
tú sabes que no

00:00:07.500 --> 00:00:09.000
no, no lo sé
"""


def _write(tmp_path: Path, body: str) -> str:
    path = tmp_path / "video.en.vtt"
    path.write_text(body, encoding="utf-8")
    return str(path)


def test_rolling_captions_carry_each_word_once(tmp_path):
    segments = transcribe.parse_vtt(_write(tmp_path, ROLLING))
    words = " ".join(s["text"] for s in segments).split()
    assert words == (
        "hi everyone welcome to experience League live my name is Betsy "
        "for today it's my first time"
    ).split()


def test_rolling_captions_keep_start_times(tmp_path):
    segments = transcribe.parse_vtt(_write(tmp_path, ROLLING))
    assert [s["start"] for s in segments] == [250.88, 253.68, 255.8]


def test_manual_subtitles_pass_through(tmp_path):
    segments = transcribe.parse_vtt(_write(tmp_path, MANUAL))
    assert [s["text"] for s in segments] == [
        "Hola, ¿cómo estás?", "Bien, bien. ¿Y tú?", "tú sabes que no", "no, no lo sé",
    ]


def test_single_shared_word_is_not_stripped():
    """'…que no' / 'no, no lo sé' share one word by chance, not by rolling."""
    assert transcribe._new_words(["que", "no"], ["no,", "no", "lo", "sé"]) == ["no,", "no", "lo", "sé"]
    assert transcribe._new_words(["sabes", "que", "no"], ["no", "lo", "sé"]) == ["no", "lo", "sé"]


def test_full_repeat_is_dropped():
    assert transcribe._new_words(["a", "b", "c"], ["b", "c"]) == []
    assert transcribe._new_words(["a", "b", "c"], ["c"]) == []


def test_blocks_cap_at_ten_seconds():
    segs = [{"start": float(t), "end": float(t) + 2.0, "text": f"w{t}"} for t in range(0, 30, 2)]
    blocks = transcribe.group_blocks(segs)
    assert [b["start"] for b in blocks] == [0.0, 10.0, 20.0]
    assert all(b["end"] - b["start"] <= 12.0 for b in blocks)


def test_blocks_break_on_pauses():
    segs = [
        {"start": 0.0, "end": 2.0, "text": "antes"},
        {"start": 6.0, "end": 8.0, "text": "después"},  # 4 s of silence
    ]
    assert len(transcribe.group_blocks(segs)) == 2


def test_format_uses_one_stamp_per_block_and_hours():
    segs = [
        {"start": 3725.0, "end": 3727.0, "text": "una"},
        {"start": 3727.0, "end": 3729.0, "text": "frase"},
    ]
    assert transcribe.format_transcript(segs) == "[1:02:05] una frase"
