from __future__ import annotations

import io
import threading
from dataclasses import dataclass
from functools import lru_cache

from .config import settings


ACCEPTED_AUDIO_TYPES = {
    "audio/aac",
    "audio/flac",
    "audio/m4a",
    "audio/mp3",
    "audio/mp4",
    "audio/mpeg",
    "audio/ogg",
    "audio/wav",
    "audio/webm",
    "video/mp4",  # Safari can label an audio-only recording as video/mp4.
}


class SpeechToTextError(RuntimeError):
    pass


@dataclass(frozen=True)
class Transcription:
    text: str


class LocalSpeechToTextClient:
    """Offline speech recognition backed by a local faster-whisper model.

    The uploaded bytes are decoded from an in-memory buffer. No recording is
    written to the application data directory; only the downloaded model is
    cached there for reuse between container restarts.
    """

    def __init__(self):
        self._model = None
        self._model_lock = threading.Lock()
        self._transcribe_lock = threading.Lock()

    def _get_model(self):
        if self._model is None:
            with self._model_lock:
                if self._model is None:
                    try:
                        from faster_whisper import WhisperModel

                        self._model = WhisperModel(
                            settings.local_asr_model,
                            device="cpu",
                            compute_type=settings.local_asr_compute_type,
                            download_root=settings.local_asr_model_dir or None,
                        )
                    except Exception as exc:  # pragma: no cover - depends on runtime/model download
                        raise SpeechToTextError(
                            "本地语音模型初始化失败，请确认 faster-whisper 已安装且模型可以下载；"
                            f"模型：{settings.local_asr_model}（{exc}）"
                        ) from exc
        return self._model

    def transcribe(self, filename: str, content: bytes, content_type: str) -> Transcription:
        del filename, content_type  # The decoder detects the container from its bytes.
        try:
            # faster-whisper delegates decoding to PyAV, which accepts a
            # seekable file-like object and keeps the uploaded recording in RAM.
            with self._transcribe_lock:
                segments, info = self._get_model().transcribe(
                    io.BytesIO(content),
                    language=settings.local_asr_language or None,
                    beam_size=5,
                    condition_on_previous_text=False,
                    vad_filter=True,
                )
                duration = getattr(info, "duration", None)
                if duration is not None and duration > settings.max_audio_seconds:
                    raise SpeechToTextError(f"单段录音不能超过 {settings.max_audio_seconds} 秒。")
                text = "".join(segment.text for segment in segments).strip()
        except SpeechToTextError:
            raise
        except Exception as exc:
            raise SpeechToTextError(f"本地语音转文字失败：{exc}") from exc
        if not text:
            raise SpeechToTextError("没有识别到清晰语音，请靠近麦克风后重试。")
        return Transcription(text=text)


class DemoSpeechToTextClient(LocalSpeechToTextClient):
    def transcribe(self, filename: str, content: bytes, content_type: str) -> Transcription:
        return Transcription(text="这是本地测试模式识别出的口语回答。")


@lru_cache(maxsize=1)
def provider() -> LocalSpeechToTextClient:
    return DemoSpeechToTextClient() if settings.mock_mimo else LocalSpeechToTextClient()


def is_enabled() -> bool:
    if settings.mock_mimo:
        return True
    if not settings.local_asr_enabled:
        return False
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True
