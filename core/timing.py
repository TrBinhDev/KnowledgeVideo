import logging
import tempfile
from pathlib import Path

from core.video_pipeline import probe, run_tts, synthesize

logger = logging.getLogger("kv.timing")

# Edge TTS still sounds natural within roughly ±10% speed; beyond that the script itself must change.
MAX_RATE_PERCENT = 10
TOLERANCE_SECONDS = 3.0
_ATTEMPTS = 3


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
    """Pick the speaking rate that lands the audio within TOLERANCE_SECONDS of the target, verified by re-measuring."""
    def report(message: str) -> None:
        if progress:
            progress(message, -1)

    if measured_seconds is None:
        base = measure(text, voice)
        report(f"Đo giọng đọc: {base:.1f}s / mục tiêu {target_seconds:.0f}s")
    else:
        base = measured_seconds
    percent, seconds = 0, base
    for _ in range(2):
        if abs(seconds - target_seconds) <= TOLERANCE_SECONDS:
            break
        wanted = rate_for(seconds, target_seconds, percent)
        if wanted == percent:
            break
        percent = wanted
        seconds = measure(text, voice, percent)
        report(f"Chỉnh tốc độ đọc {rate_text(percent)}: {seconds:.1f}s")
    return {
        "voice": voice,
        "tts_rate": rate_text(percent),
        "base_seconds": round(base, 1),
        "seconds": round(seconds, 1),
        "target_seconds": target_seconds,
        "within_tolerance": abs(seconds - target_seconds) <= TOLERANCE_SECONDS,
        "narration": text,
    }
