import hashlib
import json
import logging
import os
import shutil
import tempfile
from pathlib import Path

from core.config import output_directory
from core.video_pipeline import probe, run_media, run_tts, synthesize

logger = logging.getLogger("kv.timing")
# Measured narrations kept for the render (a few, one per recent script and voice).
_KEPT_VOICES = 6

# Edge TTS still sounds natural within roughly ±10% speed; beyond that the script itself must change.
MAX_RATE_PERCENT = 10
# Allowed final difference from the target: 5% of the length, at least 3 s (60 s: ±3 s, 300 s: ±15 s).
TOLERANCE_SHARE = 0.05
TOLERANCE_SECONDS = 3.0
_ATTEMPTS = 3


def tolerance(target_seconds: float) -> float:
    return max(TOLERANCE_SECONDS, TOLERANCE_SHARE * target_seconds)


def narration(script: dict) -> str:
    """Exactly what the render pipeline reads aloud."""
    return script["hook"].strip() + "\n\n" + script["body"].strip()


def rate_text(percent: int) -> str:
    return f"{percent:+d}%"


def _voice_cache() -> Path:
    directory = output_directory() / "_voice_cache"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _voice_key(text: str, voice: str) -> str:
    return hashlib.sha1(f"{voice}|{text}".encode("utf-8")).hexdigest()[:20]


def _keep_voice(text: str, voice: str, audio: Path, words: list, sentences: list) -> None:
    """Keep a measurement's audio and cues so the render can use them instead of reading the script again."""
    directory, key = _voice_cache(), _voice_key(text, voice)
    shutil.copyfile(audio, directory / f"{key}.mp3")
    (directory / f"{key}.json").write_text(json.dumps({"words": words, "sentences": sentences}, ensure_ascii=False),
                                           encoding="utf-8")
    kept = sorted(directory.glob("*.mp3"), key=lambda path: path.stat().st_mtime, reverse=True)
    for old in kept[_KEPT_VOICES:]:
        old.unlink(missing_ok=True)
        old.with_suffix(".json").unlink(missing_ok=True)


def measure(text: str, voice: str, rate_percent: int = 0) -> float:
    """Synthesize for real and return the audio length in seconds (retries if Edge TTS cuts the stream).

    At the normal rate the audio is kept (see reuse_or_synthesize)."""
    with tempfile.TemporaryDirectory(prefix="kv_measure_") as directory:
        folder = Path(directory)
        for attempt in range(_ATTEMPTS):
            words: list = []
            cues = run_tts(synthesize(text, voice, folder, rate_text(rate_percent), word_cues=words), text)
            duration = float(probe(folder / "voice.mp3")["format"]["duration"])
            if duration >= cues[-1][0] + 0.5:
                if rate_percent == 0:
                    _keep_voice(text, voice, folder / "voice.mp3", words, cues)
                return duration
            logger.warning("measure_audio_truncated attempt=%d audio=%.1fs", attempt + 1, duration)
    raise RuntimeError("Giọng đọc TTS bị cắt ngang khi đo thời lượng. Kiểm tra mạng rồi thử lại.")


async def reuse_or_synthesize(text, voice, directory, rate="+0%", word_cues: list | None = None):
    """Same contract as video_pipeline.synthesize, but reuses the audio measured in the script step when the text
    and voice are unchanged: ffmpeg atempo brings it to `rate` (pitch kept) and the cues are scaled to match.
    Edge TTS reads at about real-time speed, so this saves minutes on long videos."""
    cache, key = _voice_cache(), _voice_key(text, voice)
    audio, cues_file = cache / f"{key}.mp3", cache / f"{key}.json"
    if audio.is_file() and cues_file.is_file():
        try:
            kept = json.loads(cues_file.read_text(encoding="utf-8"))
            factor = 1 + int(rate.rstrip("%")) / 100
            run_media(["ffmpeg", "-y", "-nostdin", "-v", "error", "-i", str(audio), "-filter:a", f"atempo={factor:.4f}",
                       "-c:a", "libmp3lame", "-b:a", "128k", "voice.mp3"], directory, 300)
        except (ValueError, OSError, RuntimeError) as error:
            logger.warning("voice_reuse_failed reason=%s", type(error).__name__)
        else:
            os.utime(audio)
            scaled = lambda cues: [(start / factor, end / factor, content) for start, end, content in cues]
            if word_cues is not None:
                word_cues[:] = scaled(kept["words"])
            logger.info("voice_reused rate=%s", rate)
            return scaled(kept["sentences"])
    return await synthesize(text, voice, directory, rate, word_cues)


def rate_for(measured_seconds: float, target_seconds: float, measured_rate_percent: int = 0) -> int:
    """Edge TTS duration scales about 1/(1+rate): recover the unrated length, then solve for the target."""
    unrated = measured_seconds * (1 + measured_rate_percent / 100)
    percent = round((unrated / target_seconds - 1) * 100)
    return max(-MAX_RATE_PERCENT, min(MAX_RATE_PERCENT, percent))


def fit_rate(text: str, voice: str, target_seconds: float, progress=None, measured_seconds: float | None = None) -> dict:
    """Pick the speaking rate that brings the audio to the target.

    The length at that rate is computed (duration scales about 1/(1+rate)) instead of synthesizing again: each
    measurement reads the whole script aloud, which took minutes for long videos. The render measures the real
    audio anyway.
    """
    def report(message: str) -> None:
        if progress:
            progress(message, -1)

    if measured_seconds is None:
        base = measure(text, voice)
        report(f"Đo giọng đọc: {base:.1f}s / mục tiêu {target_seconds:.0f}s")
    else:
        base = measured_seconds
    percent = 0 if abs(base - target_seconds) <= tolerance(target_seconds) else rate_for(base, target_seconds)
    seconds = base / (1 + percent / 100)
    if percent:
        report(f"Chỉnh tốc độ đọc {rate_text(percent)}: ~{seconds:.1f}s")
    return {
        "voice": voice,
        "tts_rate": rate_text(percent),
        "base_seconds": round(base, 1),
        "seconds": round(seconds, 1),
        "target_seconds": target_seconds,
        "within_tolerance": abs(seconds - target_seconds) <= tolerance(target_seconds),
        "narration": text,
    }
