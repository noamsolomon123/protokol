"""LocalWhisperTranscriber: free, unlimited, private Hebrew transcription on THIS
PC via faster-whisper + an ivrit.ai Hebrew-fine-tuned Whisper model.

Why local in addition to Gemini: no rate limits, no per-call quota, nothing
leaves the machine, and ivrit.ai's Hebrew fine-tune beats vanilla Whisper on
Hebrew. Auto-uses the GPU (CUDA float16) when available and falls back to CPU
(int8). Exposes the SAME interface as GeminiTranscriber (`transcribe_file(path)
-> list[Segment]`), so the two engines are interchangeable.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

from knesset_osint.core.logging import get_logger
from knesset_osint.ingestion.transcription.gemini import Segment  # shared dataclass

logger = get_logger("transcription.local")

# ivrit.ai Hebrew fine-tune, CTranslate2 format (turbo = fast, large-v3 quality).
DEFAULT_MODEL = "ivrit-ai/whisper-large-v3-turbo-ct2"


def _add_nvidia_dll_dirs() -> None:
    """On Windows, make the pip-installed cuDNN/cuBLAS DLLs discoverable so
    CTranslate2 can use the GPU. CTranslate2 loads these via plain LoadLibrary,
    which searches PATH (NOT the add_dll_directory list) — so we do both, and
    this must run BEFORE faster-whisper/ctranslate2 loads the CUDA libs."""
    if sys.platform != "win32":
        return
    for pkg in ("nvidia.cublas", "nvidia.cudnn"):
        spec = importlib.util.find_spec(pkg)
        if not spec or not spec.submodule_search_locations:
            continue
        bindir = Path(list(spec.submodule_search_locations)[0]) / "bin"
        if bindir.is_dir():
            b = str(bindir)
            try:
                os.add_dll_directory(b)
            except (OSError, AttributeError):
                pass
            if b not in os.environ.get("PATH", ""):
                os.environ["PATH"] = b + os.pathsep + os.environ.get("PATH", "")


def _detect_device() -> tuple[str, str]:
    """Return (device, compute_type): CUDA float16 if a GPU is present, else CPU int8."""
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda", "float16"
    except Exception:  # noqa: BLE001 - any failure -> CPU
        pass
    return "cpu", "int8"


class LocalWhisperTranscriber:
    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        language: str = "he",
        device: str | None = None,
        compute_type: str | None = None,
    ) -> None:
        _add_nvidia_dll_dirs()
        from faster_whisper import WhisperModel

        dev, ct = _detect_device()
        self.device = device or dev
        self.compute_type = compute_type or ct
        self.language = language
        self.model_name = model

        logger.info(
            "Loading faster-whisper model=%s device=%s compute=%s", model, self.device, self.compute_type
        )
        try:
            self._model = WhisperModel(model, device=self.device, compute_type=self.compute_type)
        except Exception as e:  # noqa: BLE001 - GPU/driver issues -> CPU fallback
            if self.device != "cpu":
                logger.warning("GPU model load failed (%s); falling back to CPU int8.", e)
                self.device, self.compute_type = "cpu", "int8"
                self._model = WhisperModel(model, device="cpu", compute_type="int8")
            else:
                raise

    def transcribe_file(self, path: str | Path) -> list[Segment]:
        """Transcribe an audio file to timestamped Hebrew segments (sentence-level)."""
        segments, _info = self._model.transcribe(
            str(path),
            language=self.language,
            vad_filter=True,  # skip silence -> cleaner segments
            beam_size=5,
        )
        out: list[Segment] = []
        for s in segments:
            text = (s.text or "").strip()
            if text:
                out.append(Segment(float(s.start), float(s.end), text))
        return out
