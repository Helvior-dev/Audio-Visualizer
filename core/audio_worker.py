"""
Audio worker thread and manager for PyQt6 integration.
Coordinates AudioCaptureEngine with Qt event loop and signals.
"""

from PyQt6.QtCore import QObject, pyqtSignal, QThread
from .audio_capture import AudioCaptureEngine, AudioSource, list_audio_sources
from typing import Tuple, Optional
import numpy as np


class AudioWorker(QObject):
    """
    QObject worker running inside a dedicated QThread or managing the audio capture pipeline.
    """
    device_changed = pyqtSignal(str)
    stream_error = pyqtSignal(str)

    def __init__(self, source: Optional[AudioSource] = None):
        super().__init__()
        self.source = source or AudioSource()
        self.engine = AudioCaptureEngine(chunk_size=1024, source=self.source)

    def change_source(self, source: AudioSource):
        self.source = source
        self.engine.reopen(source)
        if self.engine.last_error:
            self.stream_error.emit(self.engine.last_error)
        else:
            self.device_changed.emit(self.source.name)

    def get_latest_samples(self, num_samples: int) -> Tuple[np.ndarray, int, int]:
        """Fetch the most recent N samples (shape: [num_samples, channels]), sample_rate, channels."""
        return self.engine.get_latest_frames(num_samples)

    def create_reader(self, chunk_size: int = 1024):
        return self.engine.create_reader(chunk_size=chunk_size)

    def is_active(self) -> bool:
        return self.engine.is_running

    def close(self):
        self.engine.close()
