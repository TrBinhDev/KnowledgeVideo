import logging
import tempfile
from pathlib import Path

from core.video_pipeline import probe, run_tts, synthesize

logger = logging.getLogger("kv.timing")

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


def measure(text: str, voice: str, rate_percent: int = 0) -> float:
    """Synthesize for real and return the audio length in seconds (retries if Edge TTS cuts the stream)."""
    with tempfile.TemporaryDirectory(prefix="kv_measure_") as directory:
        folder = Path(directory)
        for attempt in range(_ATTEMPTS):
            cues = run_tts(synthesize(text, voice, folder, rate_text(rate_percent)), text)
            duration = float(probe(folder / "voice.mp3")["format"]["duration"])
            if duration >= cues[-1][0] + 0.5:
                return duration
            logger.warning("measure_audio_truncated attempt=%d audio=%.1fs", attempt + 1, duration)
    raise RuntimeError("Giọng đọc TTS bị cắt ngang khi đo thời lượng. Kiểm tra mạng rồi thử lại.")


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
