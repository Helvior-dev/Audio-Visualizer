"""
Audio capture subsystem using WASAPI Loopback and PyAudioWPatch.
Provides enumerating audio sources (System loopback audio devices and Microphones)
and streaming low-latency PCM buffers.
"""

import sys
import time
import struct
import numpy as np
import pyaudiowpatch as pyaudio
from dataclasses import dataclass
from typing import List, Tuple, Optional, Callable
import multiprocessing.shared_memory as shm

KIND_LOOPBACK = "loopback"
KIND_MICROPHONE = "microphone"
SHM_NAME = "audio_visualizer_shm_v2"
SILENCE_TIMEOUT_SEC = 0.2


@dataclass(frozen=True)
class AudioSource:
    kind: str = KIND_LOOPBACK
    device_index: Optional[int] = None
    name: str = "Default system audio"

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "device_index": self.device_index,
            "name": self.name
        }

    @staticmethod
    def from_dict(d: dict) -> "AudioSource":
        return AudioSource(
            kind=d.get("kind", KIND_LOOPBACK),
            device_index=d.get("device_index"),
            name=d.get("name", "Default system audio"),
        )


def list_audio_sources() -> Tuple[List[AudioSource], List[AudioSource]]:
    """Enumerate all available WASAPI loopback and microphone sources."""
    pa = pyaudio.PyAudio()
    try:
        loopback_sources = [AudioSource(KIND_LOOPBACK, None, "Default system audio")]
        mic_sources = [AudioSource(KIND_MICROPHONE, None, "Default microphone")]

        seen_loopback_names = set()
        for dev in pa.get_loopback_device_info_generator():
            name = dev["name"]
            if name in seen_loopback_names:
                continue
            seen_loopback_names.add(name)
            loopback_sources.append(AudioSource(KIND_LOOPBACK, dev["index"], name))

        try:
            wasapi_info = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        except OSError:
            wasapi_info = None

        if wasapi_info is not None:
            for i in range(pa.get_device_count()):
                dev = pa.get_device_info_by_index(i)
                if dev.get("hostApi") != wasapi_info["index"]:
                    continue
                if dev.get("isLoopbackDevice", False):
                    continue
                if int(dev.get("maxInputChannels", 0)) <= 0:
                    continue
                mic_sources.append(AudioSource(KIND_MICROPHONE, dev["index"], dev["name"]))

        return loopback_sources, mic_sources
    finally:
        pa.terminate()


class AudioCaptureEngine:
    """
    Manages low-latency audio capture stream and maintains a lock-free circular buffer.
    Supports in-process callbacks and IPC via shared memory.
    """
    def __init__(self, chunk_size: int = 1024, source: Optional[AudioSource] = None):
        self.chunk_size = chunk_size
        self.pa = pyaudio.PyAudio()
        self.stream = None
        self.channels = 2
        self.rate = 44100
        self.source = source or AudioSource()
        self.last_error = None
        self.is_running = False
        
        # 1-second circular buffer
        self.buffer_frames = 44100
        self.ring_buffer = np.zeros((self.buffer_frames, 2), dtype=np.float32)
        self.write_index = 0
        
        # Callbacks for subscribers
        self._callbacks: List[Callable[[np.ndarray, int, int], None]] = []

        # Optional SharedMemory for cross-process compatibility
        bytes_size = 32 + self.buffer_frames * 2 * 4
        try:
            self.shm = shm.SharedMemory(name=SHM_NAME, create=True, size=bytes_size)
        except FileExistsError:
            try:
                self.shm = shm.SharedMemory(name=SHM_NAME, create=False)
            except Exception:
                self.shm = None
        except Exception:
            self.shm = None

        self._open_stream(self.source)

    def subscribe(self, callback: Callable[[np.ndarray, int, int], None]):
        """Subscribe a callback receiving (audio_chunk_float32, sample_rate, channels)."""
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def unsubscribe(self, callback: Callable[[np.ndarray, int, int], None]):
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def _write_header(self, active=1):
        if self.shm is not None:
            try:
                header = struct.pack("iiiiqi", 0x41554449, self.channels, self.rate, self.buffer_frames, self.write_index, active)
                self.shm.buf[:28] = header
            except Exception:
                pass

    def _resolve_device(self, source: AudioSource) -> dict:
        if source.device_index is not None:
            try:
                return self.pa.get_device_info_by_index(source.device_index)
            except Exception:
                pass

        try:
            wasapi_info = self.pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        except OSError:
            raise RuntimeError("WASAPI host API is not available on this system.")

        if source.kind == KIND_MICROPHONE:
            try:
                default_in = self.pa.get_default_input_device_info()
                if default_in.get("hostApi") == wasapi_info["index"]:
                    return default_in
            except Exception:
                pass
            for i in range(self.pa.get_device_count()):
                dev = self.pa.get_device_info_by_index(i)
                if dev.get("hostApi") == wasapi_info["index"] and not dev.get("isLoopbackDevice", False) and dev.get("maxInputChannels", 0) > 0:
                    return dev

        # Default loopback
        try:
            return self.pa.get_default_wasapi_loopback()
        except Exception:
            pass

        try:
            default_out = self.pa.get_default_output_device_info()
            for dev in self.pa.get_loopback_device_info_generator():
                if dev.get("name") == default_out.get("name"):
                    return dev
            for dev in self.pa.get_loopback_device_info_generator():
                return dev
        except Exception:
            pass

        raise RuntimeError("No suitable audio device found.")

    def _open_stream(self, source: AudioSource):
        self._close_stream()
        self.source = source
        self.last_error = None

        try:
            dev_info = self._resolve_device(source)
            self.rate = int(dev_info.get("defaultSampleRate", 44100))
            max_in = int(dev_info.get("maxInputChannels", 2))
            self.channels = min(2, max(1, max_in))

            def _audio_callback(in_data, frame_count, time_info, status):
                if in_data is not None and len(in_data) > 0:
                    try:
                        audio = np.frombuffer(in_data, dtype=np.float32)
                        n_frames = len(audio) // self.channels
                        if n_frames > 0:
                            samples = audio.reshape((n_frames, self.channels))

                            if self.channels == 1:
                                stereo_samples = np.column_stack([samples[:, 0], samples[:, 0]])
                            else:
                                stereo_samples = samples[:, :2]

                            # Write to internal circular buffer
                            w_idx = self.write_index
                            end_idx = w_idx + n_frames
                            if end_idx <= self.buffer_frames:
                                self.ring_buffer[w_idx:end_idx] = stereo_samples
                            else:
                                first_part = self.buffer_frames - w_idx
                                second_part = n_frames - first_part
                                self.ring_buffer[w_idx:] = stereo_samples[:first_part]
                                self.ring_buffer[:second_part] = stereo_samples[first_part:]
                            self.write_index = (w_idx + n_frames) % self.buffer_frames

                            # Write to shared memory if active
                            if self.shm is not None:
                                try:
                                    buf_offset = 32
                                    if end_idx <= self.buffer_frames:
                                        self.shm.buf[buf_offset + w_idx * 8 : buf_offset + end_idx * 8] = stereo_samples.tobytes()
                                    else:
                                        self.shm.buf[buf_offset + w_idx * 8 :] = stereo_samples[:first_part].tobytes()
                                        self.shm.buf[buf_offset : buf_offset + second_part * 8] = stereo_samples[first_part:].tobytes()
                                    self._write_header(1)
                                except Exception:
                                    pass

                            # Notify direct subscribers
                            for cb in list(self._callbacks):
                                try:
                                    cb(stereo_samples, self.rate, self.channels)
                                except Exception:
                                    pass
                    except Exception:
                        pass
                return (None, pyaudio.paContinue)

            self.stream = self.pa.open(
                format=pyaudio.paFloat32,
                channels=self.channels,
                rate=self.rate,
                input=True,
                input_device_index=dev_info["index"],
                frames_per_buffer=self.chunk_size,
                stream_callback=_audio_callback
            )
            self.stream.start_stream()
            self.is_running = True
        except Exception as e:
            self.last_error = str(e)
            print(f"Failed to open audio stream: {e}")
            self.is_running = False

    def _close_stream(self):
        if self.stream is not None:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception:
                pass
            self.stream = None
        self.is_running = False

    def create_reader(self, chunk_size: int = 1024) -> "AudioCaptureReader":
        return AudioCaptureReader(self, chunk_size=chunk_size)

    def change_source(self, new_source: AudioSource):
        """Switch audio capture device without restarting the app."""
        self._open_stream(new_source)

    def reopen(self, new_source: AudioSource):
        self.change_source(new_source)

    def close(self):
        self._close_stream()
        if self.shm is not None:
            try:
                self._write_header(0)
                self.shm.close()
                self.shm.unlink()
            except Exception:
                pass
            self.shm = None
        self.pa.terminate()


class AudioCaptureReader:
    """
    Subscribes to an AudioWorker/AudioCaptureEngine and pulls chunks for a single visualizer.
    """
    def __init__(self, engine: AudioCaptureEngine, chunk_size: int = 1024):
        self.engine = engine
        self.chunk_size = chunk_size
        self.last_read_index = engine.write_index

    def read_chunk(self) -> Optional[Tuple[np.ndarray, int, int]]:
        curr_w = self.engine.write_index
        r_idx = self.last_read_index
        total_buf = self.engine.buffer_frames

        if curr_w >= r_idx:
            avail = curr_w - r_idx
        else:
            avail = (total_buf - r_idx) + curr_w

        if avail < 32:
            return None

        take_frames = min(avail, total_buf // 2)
        end_idx = (r_idx + take_frames) % total_buf

        if r_idx + take_frames <= total_buf:
            chunk = self.engine.ring_buffer[r_idx:r_idx + take_frames].copy()
        else:
            first = total_buf - r_idx
            second = take_frames - first
            chunk = np.vstack([self.engine.ring_buffer[r_idx:], self.engine.ring_buffer[:second]])

        self.last_read_index = end_idx
        return chunk, self.engine.rate, self.engine.channels
