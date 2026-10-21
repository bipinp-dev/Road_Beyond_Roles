"""Text-to-speech (edge-tts) and ffmpeg video assembly."""
import asyncio
import hashlib
import logging
import os
import re
import subprocess
import shutil
from pathlib import Path

log = logging.getLogger("media")
PAD = 0.6  # seconds of breathing room after each scene

_ROMAN_TO_WORD = {
    "II": "two", "III": "three", "IV": "four",
    "VI": "six", "VII": "seven", "VIII": "eight", "IX": "nine",
    "XI": "eleven", "XII": "twelve", "XIII": "thirteen",
    "XIV": "fourteen", "XV": "fifteen", "XVI": "sixteen",
    "XVII": "seventeen", "XVIII": "eighteen", "XIX": "nineteen",
    "XX": "twenty",
}
_ROMAN_RE = re.compile(r"\b(" + "|".join(_ROMAN_TO_WORD.keys()) + r")\b")

def _fix_pronunciation(text: str) -> str:
    return _ROMAN_RE.sub(lambda mm: _ROMAN_TO_WORD[mm.group(0)], text)


def run(cmd: list[str], timeout: int = 300):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"{cmd[0]} timed out after {timeout}s: " + " ".join(str(x) for x in cmd)[:250]
        )
    if r.returncode:
        raise RuntimeError(f"{cmd[0]} failed: {r.stderr[-1500:]}")
    return r.stdout


def duration(path) -> float:
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                      "-of", "csv=p=0", str(path)]).strip())


# ------------------------------------------------------------------ TTS
def tts(text: str, out: Path, backend="edge", voice="en-IN-NeerjaNeural", rate="+4%", force: bool = False) -> Path:
    """Generate cached narration using Edge TTS, Kokoro CPU, or silent test audio.

    `force=True` bypasses the content-hash cache and always regenerates audio.
    """
    text = _fix_pronunciation(text)
    out.parent.mkdir(parents=True, exist_ok=True)
    speed_key = os.environ.get("KOKORO_SPEED", "1.10") if backend == "kokoro" else ""
    h = hashlib.sha1(f"{backend}|{voice}|{rate}|{speed_key}|{text}".encode("utf-8")).hexdigest()[:10]
    out = out.with_name(f"{out.stem}_{h}.mp3")
    if not force and out.exists() and out.stat().st_size > 1000:
        return out

    if backend == "silent":
        secs = max(2.0, len(text.split()) / 2.6)
        run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
            "-t", f"{secs:.2f}", "-c:a", "libmp3lame", "-q:a", "9", str(out),
        ])
        return out

    if backend == "kokoro":
        kokoro_python = os.environ.get(
            "KOKORO_PYTHON",
            r"C:\Users\Bipinzzz\Downloads\Ultimate-TTS-Studio-SUP3R-Edition-main\.venv-kokoro\Scripts\python.exe",
        )
        if not Path(kokoro_python).is_file():
            raise RuntimeError(
                "Kokoro Python executable not found. Set KOKORO_PYTHON to the "
                f"environment's python.exe path. Checked: {kokoro_python}"
            )

        # Existing Edge voice names are not Kokoro voices. Default to the preset
        # already verified by the project's Kokoro test; explicit Kokoro voice
        # names can be supplied through profile.json later.
        kokoro_voice = voice if voice.startswith(("af_", "am_", "bf_", "bm_")) else "am_adam"
        wav_path = out.with_suffix(".kokoro.wav")
        lang_code = os.environ.get("KOKORO_LANG_CODE", "a")
        code = r'''import sys
import torch
import soundfile as sf
from kokoro import KPipeline

text, output, voice, lang_code = sys.argv[1:5]
speed = float(__import__("os").environ.get("KOKORO_SPEED", "1.10"))
pipeline = KPipeline(lang_code=lang_code)
chunks = [audio.cpu() for _, _, audio in pipeline(text, voice=voice, speed=speed)]
if not chunks:
    raise RuntimeError("Kokoro generated no audio")
# Keep brief breathing room between Kokoro's internal chunks so long-form narration
# does not sound like phrases have been hard-cut together.
silence = torch.zeros(int(24000 * 0.16), dtype=chunks[0].dtype)
pieces = []
for index, chunk in enumerate(chunks):
    if index:
        pieces.append(silence)
    pieces.append(chunk)
audio = torch.cat(pieces).numpy()
sf.write(output, audio, 24000)
'''
        try:
            result = subprocess.run(
                [kokoro_python, "-c", code, text, str(wav_path), kokoro_voice, lang_code],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                raise RuntimeError(f"Kokoro failed:\n{result.stderr[-2500:]}")
            if not wav_path.exists() or wav_path.stat().st_size <= 1000:
                raise RuntimeError("Kokoro finished without creating a valid WAV file")
            run([
                "ffmpeg", "-y", "-i", str(wav_path), "-codec:a", "libmp3lame",
                "-q:a", "4", str(out),
            ])
            if not out.exists() or out.stat().st_size <= 1000:
                raise RuntimeError("Kokoro output MP3 is missing or too small")
            return out
        finally:
            wav_path.unlink(missing_ok=True)

    if backend != "edge":
        raise ValueError(f"Unsupported TTS backend: {backend!r}")

    import edge_tts
    last = None
    for attempt in range(3):
        try:
            asyncio.run(edge_tts.Communicate(text, voice, rate=rate).save(str(out)))
            if out.exists() and out.stat().st_size > 1000:
                return out
            last = RuntimeError("Edge TTS produced a missing or empty audio file")
        except Exception as ex:
            last = ex
            log.warning("edge-tts attempt %d failed: %s", attempt + 1, ex)
    raise RuntimeError(f"edge-tts failed after 3 attempts: {last}")


# ------------------------------------------------------------------ video
def make_clip(
    image: Path,
    audio: Path,
    out: Path,
    motion: bool = False,
    motion_mode: str | None = None,
    pad: float | None = None,
    lead_pad: float = 0.0,
    image_is_designed: bool = False,
    scroll_from: int | None = None,
    scroll_to: int | None = None,
) -> float:
    """Encode one screenshot with synchronized narration and optional gentle motion.

    ``motion`` remains backward-compatible with existing callers. ``motion_mode``
    may be ``center``, ``left``, ``right``, ``up``, or ``down``. Each input is a
    viewport screenshot, so this adds controlled camera movement within that
    image; real page progression comes from sequencing the captured scroll-position
    screenshots as separate scenes. Source screenshots are never modified.
    """
    pad_value = PAD if pad is None else max(0.0, float(pad))
    lead_pad = max(0.0, float(lead_pad))
    _raw_dur = duration(audio)
    dur = max(0.1, min(_raw_dur + pad_value + lead_pad, 600.0))
    if _raw_dur + pad_value + lead_pad > 600.0:
        log.warning("Clip %s duration capped at 600s (raw=%.2fs)", out.name, _raw_dur)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Detect input size so crop only applies to full-1920 screenshots.
    # Smaller inputs (banner) use scale+pad instead.
    import subprocess as _sp
    _probe = _sp.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(image)],
        capture_output=True, text=True,
    ).stdout.strip()
    try:
        _w, _h = (int(x) for x in _probe.split(",")[:2])
    except (ValueError, IndexError):
        _w, _h = 0, 0

    if scroll_from is not None and scroll_to is not None and _h > 1100:
        max_to = max(0, _h - 1080)
        sf = max(0, min(int(scroll_from), max_to))
        st = max(0, min(int(scroll_to), max_to))
        y_expr = f"min(max(0,{sf}+({st}-{sf})*min(t/{dur:.3f},1)),ih-1080)"
        video_filter = (
            f"crop=w=1400:h=1080:x=260:y='{y_expr}',"
            "scale=1920:1080:flags=bilinear,"
            "format=yuv420p,setsar=1"
        )
        still_image = False
    elif image_is_designed:
        # Designed slides (title cards, banner, homepage) must never be cropped.
        base = (
            "scale=1920:1080:force_original_aspect_ratio=decrease:flags=lanczos,"
            "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=white,"
            "setsar=1"
        )
    elif _w >= 1920 and _h >= 1080:
        # Screenshots and heading crops: crop 260px white margin each side.
        base = (
            "crop=1400:1080:260:0,"
            "scale=1920:1080:flags=lanczos,"
            "setsar=1"
        )
    else:
        # Small assets (banner, heading crops < 1920): preserve aspect, pad.
        base = (
            "scale=1920:1080:force_original_aspect_ratio=decrease:flags=lanczos,"
            "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black,"
            "setsar=1"
        )

    mode = (motion_mode or ("center" if motion else "static")).lower()
    allowed_modes = {"static", "center", "left", "right", "up", "down"}
    if mode not in allowed_modes:
        raise ValueError(f"Unsupported motion_mode {mode!r}; choose one of {sorted(allowed_modes)}")

    _is_scroll = scroll_from is not None and scroll_to is not None and _h > 1100
    if _is_scroll:
        pass  # video_filter already set by scroll branch above
    elif image_is_designed or mode == "static":
        video_filter = base + ",format=yuv420p"
        still_image = True
    else:
        # Very subtle center-anchored zoom. No directional pan. 5% max zoom,
        # linear over full clip duration so it never feels jittery.
        t_norm = f"min(on/max(1,{dur:.3f}*60),1)"
        smooth = f"(3*{t_norm}*{t_norm}-2*{t_norm}*{t_norm}*{t_norm})"
        zoom = f"(1+0.10*{smooth})"
        video_filter = (
            base
            + f",zoompan=z='{zoom}':x='(iw-iw/zoom)*0.5':y='(ih-ih/zoom)*0.5':"
              "d=1:s=1920x1080:fps=60,format=yuv420p"
        )
        still_image = False

    # Explicitly cap output to narration plus breathing room; apad prevents a
    # short audio stream from ending the video early. Audio is not time-stretched.
    audio_chain = "aresample=44100"
    if lead_pad > 0:
        ms = int(lead_pad * 1000)
        audio_chain += f",adelay={ms}|{ms}"
    audio_chain += f",apad=pad_dur={pad_value}"
    vf = f"[0:v]{video_filter}[v];[1:a]{audio_chain}[a]"
    _scroll_flag = scroll_from is not None and scroll_to is not None and _h > 1100
    _input_fps = "24" if _scroll_flag else "60"
    _output_fps = "24" if _scroll_flag else "60"
    _preset = "veryfast" if _scroll_flag else "medium"
    _crf = "22" if _scroll_flag else "18"
    log.info("Encoding %s: dur=%.2fs scroll=%s fps=%s",
             out.name, dur, _scroll_flag, _input_fps)
    cmd = [
        "ffmpeg", "-y", "-nostats", "-loglevel", "error",
        "-loop", "1", "-framerate", _input_fps, "-i", str(image),
        "-i", str(audio), "-filter_complex", vf, "-map", "[v]", "-map", "[a]",
        "-t", f"{dur:.3f}", "-c:v", "libx264", "-preset", _preset,
        "-crf", _crf,
    ]
    if still_image:
        cmd += ["-tune", "stillimage"]
    cmd += [
        "-r", _output_fps, "-g", _output_fps, "-profile:v", "high", "-level", "4.1", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        "-ar", "44100", "-ac", "2", "-movflags", "+faststart", str(out),
    ]
    run(cmd)
    return dur


def concat(clips: list[Path], out: Path, music: Path | None = None, narration: Path | None = None):
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{c.resolve().as_posix()}'\n" for c in clips), encoding="utf-8")
    raw = out.with_name("_video_only_concat.mp4")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(raw)])
    if narration and narration.exists():
        inputs = ["ffmpeg", "-y", "-i", str(raw), "-i", str(narration)]
        if music and music.exists():
            inputs += ["-stream_loop", "-1", "-i", str(music), "-filter_complex",
                       "[1:a]aresample=44100,volume=1.0[voice];[2:a]aresample=44100,volume=0.045[m];[voice][m]amix=inputs=2:duration=first:dropout_transition=2[a]"]
            map_audio = "[a]"
        else:
            inputs += ["-map", "1:a"]
            map_audio = None
        inputs += ["-map", "0:v"]
        if map_audio:
            inputs += ["-map", map_audio]
        inputs += ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(out)]
        run(inputs)
    elif music and music.exists():
        run(["ffmpeg", "-y", "-i", str(raw), "-stream_loop", "-1", "-i", str(music), "-filter_complex",
             "[1:a]volume=0.045[m];[0:a][m]amix=inputs=2:duration=first:dropout_transition=2[a]",
             "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest", str(out)])
    else:
        run(["ffmpeg", "-y", "-i", str(raw), "-c", "copy", str(out)])
    raw.unlink(missing_ok=True)



def validate_video(video: Path, narration_path: Path | None = None) -> dict:
    """Reject incomplete renders before they can be considered publishable."""
    import json
    if not video.is_file() or video.stat().st_size < 100_000:
        raise RuntimeError(f"Final video is missing or unexpectedly small: {video}")
    raw = run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(video)])
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Could not read final video metadata: {exc}") from exc
    streams = info.get("streams", [])
    video_stream = next((x for x in streams if x.get("codec_type") == "video"), None)
    audio_stream = next((x for x in streams if x.get("codec_type") == "audio"), None)
    if not video_stream or not audio_stream:
        raise RuntimeError("Final MP4 must contain both video and narration audio streams.")
    if (int(video_stream.get("width", 0)), int(video_stream.get("height", 0))) != (1920, 1080):
        raise RuntimeError(f"Final MP4 is not 1920x1080: {video_stream.get('width')}x{video_stream.get('height')}")
    if video_stream.get("codec_name") != "h264":
        raise RuntimeError(f"Unexpected video codec: {video_stream.get('codec_name')}")
    total = float((info.get("format") or {}).get("duration") or 0)
    audio_duration = float(audio_stream.get("duration") or total)
    if total <= 0 or abs(total - audio_duration) > 2.0:
        raise RuntimeError(f"Audio/video duration mismatch: video={total:.2f}s audio={audio_duration:.2f}s")
    if narration_path and narration_path.is_file():
        master_duration = duration(narration_path)
        if abs(total - master_duration) > 2.5:
            raise RuntimeError(f"Final video duration {total:.2f}s does not match narration {master_duration:.2f}s")
    return {"duration_sec": round(total, 3), "width": 1920, "height": 1080,
            "video_codec": video_stream.get("codec_name"), "audio_codec": audio_stream.get("codec_name"),
            "size_bytes": video.stat().st_size}


def burn_subtitles(video: Path, srt_path: Path) -> Path:
    """Burn captions with Windows-safe relative paths and visible, deadlock-free progress.

    The source MP4 is replaced only after FFmpeg has produced a valid captioned output.
    """
    video = Path(video).resolve()
    srt_path = Path(srt_path).resolve()
    if not video.is_file():
        raise RuntimeError(f"Video file is missing: {video}")
    if not srt_path.is_file() or srt_path.stat().st_size < 20:
        raise RuntimeError(f"Captions are missing or empty: {srt_path}")

    work_dir = video.parent
    out = video.with_name(video.stem + "_captioned.mp4")
    temporary_srt = None
    if srt_path.parent != work_dir:
        temporary_srt = work_dir / "_rbr_captions_temp.srt"
        shutil.copy2(srt_path, temporary_srt)
        local_srt = temporary_srt
    else:
        local_srt = srt_path

    # Relative path + cwd prevents the drive colon in C:\\... from being parsed as
    # an FFmpeg filter option delimiter on Windows.
    vf = (
        f"subtitles=filename='{local_srt.name}':"
        "force_style='FontName=Arial,FontSize=28,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=0,"
        "Alignment=2,MarginV=48'"
    )
    expected_duration = max(1.0, duration(video))
    cmd = [
        "ffmpeg", "-y", "-i", video.name, "-vf", vf,
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-profile:v", "high", "-level", "4.1", "-pix_fmt", "yuv420p",
        "-c:a", "copy", "-movflags", "+faststart",
        "-progress", "pipe:1", "-nostats", out.name,
    ]
    print(f"Burning subtitles into {video.name} ({expected_duration:.0f}s). FFmpeg progress follows.", flush=True)
    output_tail: list[str] = []
    last_bucket = -5
    try:
        proc = subprocess.Popen(
            cmd, cwd=str(work_dir), stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8",
            errors="replace", bufsize=1,
        )
        assert proc.stdout is not None
        for raw_line in proc.stdout:
            line = raw_line.strip()
            if not line:
                continue
            output_tail.append(line)
            if len(output_tail) > 120:
                output_tail.pop(0)
            if line.startswith("out_time_ms="):
                try:
                    elapsed = int(line.split("=", 1)[1]) / 1_000_000
                    bucket = min(100, int(elapsed * 100 / expected_duration) // 5 * 5)
                    if bucket >= last_bucket + 5:
                        print(f"Subtitle encoding: {bucket}%", flush=True)
                        last_bucket = bucket
                except (ValueError, ZeroDivisionError):
                    pass
        return_code = proc.wait()
        if return_code:
            raise RuntimeError(
                f"FFmpeg subtitle burn failed (exit {return_code}):\\n" + "\\n".join(output_tail[-80:])
            )
        if not out.is_file() or out.stat().st_size < 1_000:
            raise RuntimeError("FFmpeg did not create a valid captioned MP4 (output missing or too small).")
        # Verify the encoded result before replacing the only good source video.
        probe = run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(out)])
        import json
        info = json.loads(probe)
        streams = info.get("streams", [])
        has_video = any(x.get("codec_type") == "video" and x.get("codec_name") == "h264" for x in streams)
        has_audio = any(x.get("codec_type") == "audio" for x in streams)
        if not has_video or not has_audio:
            raise RuntimeError("Captioned output failed validation: H.264 video and audio are both required.")
        os.replace(out, video)
        print(f"Subtitle burn complete: {video}", flush=True)
        return video
    finally:
        if temporary_srt is not None:
            temporary_srt.unlink(missing_ok=True)

def _ts(sec: float, srt=True) -> str:
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def write_srt(texts: list[str], durs: list[float], path: Path):
    """One cue per sentence, time split by character count within each scene."""
    t, n, lines = 0.0, 1, []
    for text, d in zip(texts, durs):
        sents = [s for s in re.split(r"(?<=[.!?])\s+", text) if s]
        total = sum(len(s) for s in sents) or 1
        speak = d - PAD
        cur = t
        for s in sents:
            span = speak * len(s) / total
            lines.append(f"{n}\n{_ts(cur)} --> {_ts(cur + span)}\n{s}\n")
            cur += span
            n += 1
        t += d
    path.write_text("\n".join(lines), encoding="utf-8")


def chapter_stamp(sec: float) -> str:
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02}:{s:02}" if h else f"{m:02}:{s:02}"

def pad_audio_start(input_path: Path, seconds: float = 3.0) -> Path:
    """Prepend silence to an MP3 without re-encoding the original audio track."""
    if seconds <= 0:
        return input_path
    out = input_path.with_name(input_path.stem + f"_pad{int(seconds)}s.mp3")
    run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-t", f"{seconds:.3f}", "-i", "anullsrc=r=44100:cl=stereo",
        "-i", str(input_path),
        "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1[a]",
        "-map", "[a]", "-c:a", "libmp3lame", "-q:a", "4",
        str(out),
    ])
    return out


def master_tts(text: str, out: Path, backend="edge", voice="en-IN-NeerjaNeural", rate="+4%", force: bool = False) -> Path:
    """Generate one complete narration file for an entire video."""
    return tts(text, out.with_suffix(".mp3"), backend, voice, rate, force=force)

def segment_master_audio(master: Path, scene_texts: list[str], out_dir: Path, lead_pad_first_segment: float = 0.0) -> list[Path]:
    """Split a master narration approximately by scene word counts.

    This preserves the single-generation voice consistency while allowing the
    existing FFmpeg clip pipeline to time screenshots to the narration.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    total = duration(master)
    weights = [max(1, len(re.findall(r"\S+", t))) for t in scene_texts]
    total_w = sum(weights) or 1
    paths: list[Path] = []
    start = 0.0
    for i, w in enumerate(weights):
        span = total * w / total_w
        if i == len(weights) - 1:
            span = max(0.05, total - start)
        out = out_dir / f"{i:02}_segment.mp3"
        if i == 0 and lead_pad_first_segment > 0:
            run(["ffmpeg", "-y",
                 "-f", "lavfi", "-t", f"{lead_pad_first_segment:.3f}", "-i", "anullsrc=r=44100:cl=mono",
                 "-ss", f"{start:.3f}", "-t", f"{span:.3f}", "-i", str(master),
                 "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1[a]",
                 "-map", "[a]", "-c:a", "libmp3lame", "-q:a", "4", str(out)])
        else:
            run(["ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", str(master),
                 "-t", f"{span:.3f}", "-c:a", "libmp3lame", "-q:a", "4", str(out)])
        paths.append(out)
        start += span
    return paths
