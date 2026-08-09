import multiprocessing.shared_memory as shm
import struct
import time
import numpy as np
import pyaudiowpatch as pyaudio
import queue

from dataclasses import dataclass

KIND_LOOPBACK = "loopback"
KIND_MICROPHONE = "microphone"

@dataclass(frozen=True)
class AudioSource:
    kind: str = KIND_LOOPBACK
    device_index: int | None = None
    name: str = "Default system audio"

    def as_dict(self) -> dict:
        return {"kind": self.kind, "device_index": self.device_index, "name": self.name}

    @staticmethod
    def from_dict(d: dict) -> "AudioSource":
        return AudioSource(
            kind=d.get("kind", KIND_LOOPBACK),
            device_index=d.get("device_index"),
            name=d.get("name", "Default system audio"),
        )

def list_audio_sources() -> tuple[list[AudioSource], list[AudioSource]]:
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
SHM_NAME = "minimeters_audio_shm_v1"
SILENCE_TIMEOUT_SEC = 0.15

class AudioCaptureServer:
    def __init__(self, chunk_size: int = 1024, source: AudioSource | None = None):
        self.chunk_size = chunk_size
        self.pa = pyaudio.PyAudio()
        self.stream = None
        self.channels = 2
        self.rate = 44100
        self.source = source or AudioSource()
        self.last_error = None
        
        # 1 second buffer
        self.buffer_frames = 44100
        bytes_size = 32 + self.buffer_frames * 2 * 4  # max 2 channels
        
        try:
            self.shm = shm.SharedMemory(name=SHM_NAME, create=True, size=bytes_size)
        except FileExistsError:
            self.shm = shm.SharedMemory(name=SHM_NAME, create=False)
            
        self.write_index = 0
        self._write_header(active=0)
        
        self._open_stream(self.source)

    def _write_header(self, active=1):
        # int32 magic, int32 channels, int32 rate, int32 buffer_frames, int64 write_index, int32 active
        header = struct.pack("iiiiqi", 0x41554449, self.channels, self.rate, self.buffer_frames, self.write_index, active)
        self.shm.buf[:28] = header

    def _resolve_device(self, source: AudioSource) -> dict:
        if source.device_index is not None:
            return self.pa.get_device_info_by_index(source.device_index)

        try:
            wasapi_info = self.pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        except OSError:
            raise RuntimeError("WASAPI not available.")

        if source.kind == KIND_MICROPHONE:
            return self.pa.get_device_info_by_index(wasapi_info["defaultInputDevice"])

        default_speakers = self.pa.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
        if not default_speakers.get("isLoopbackDevice", False):
            for loopback in self.pa.get_loopback_device_info_generator():
                if default_speakers["name"] in loopback["name"]:
                    return loopback
            raise RuntimeError(f"Could not find loopback device for: {default_speakers['name']}")
        return default_speakers

    def _open_stream(self, source: AudioSource):
        device = self._resolve_device(source)
        self.channels = max(1, int(device.get("maxInputChannels", 2)))
        self.rate = int(device["defaultSampleRate"])
        
        self.write_index = 0
        self._write_header(active=1)

        self.stream = self.pa.open(
            format=pyaudio.paFloat32,
            channels=self.channels,
            rate=self.rate,
            frames_per_buffer=self.chunk_size,
            input=True,
            input_device_index=device["index"],
            stream_callback=self._on_audio,
        )
        self.stream.start_stream()

    def reopen(self, source: AudioSource):
        if self.stream is not None:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except OSError:
                pass
            self.stream = None

        self._write_header(active=0)
        self.last_error = None
        try:
            self._open_stream(source)
            self.source = source
        except (RuntimeError, OSError) as exc:
            self.last_error = str(exc)
            self.stream = None

    def _on_audio(self, in_data, frame_count, time_info, status):
        data = np.frombuffer(in_data, dtype=np.float32)
        
        buffer_array = np.ndarray((self.buffer_frames, self.channels), dtype=np.float32, buffer=self.shm.buf[32:])
        
        # write to ring buffer
        start_idx = self.write_index % self.buffer_frames
        end_idx = start_idx + frame_count
        
        if end_idx <= self.buffer_frames:
            buffer_array[start_idx:end_idx, :] = data.reshape(frame_count, self.channels)
        else:
            first_part = self.buffer_frames - start_idx
            second_part = frame_count - first_part
            data_reshaped = data.reshape(frame_count, self.channels)
            buffer_array[start_idx:, :] = data_reshaped[:first_part, :]
            buffer_array[:second_part, :] = data_reshaped[first_part:, :]
            
        self.write_index += frame_count
        self._write_header(active=1)
        
        return (None, pyaudio.paContinue)

    def close(self):
        if self.stream is not None:
            self.stream.stop_stream()
            self.stream.close()
        self._write_header(active=0)
        self.pa.terminate()
        try:
            self.shm.unlink()
        except Exception:
            pass


class AudioCaptureClient:
    def __init__(self, chunk_size: int = 1024, source=None):
        self.chunk_size = chunk_size
        self.channels = 2
        self.rate = 44100
        self.shm = None
        self.last_read_index = -1
        self._last_data_time = time.monotonic()
        self._silence = np.zeros((self.chunk_size, 2), dtype=np.float32)

    def _connect(self):
        try:
            self.shm = shm.SharedMemory(name=SHM_NAME, create=False)
            return True
        except FileNotFoundError:
            return False

    def reopen(self, source):
        pass

    def read_chunk(self):
        if self.shm is None:
            if not self._connect():
                return self._silence

        try:
            header_bytes = self.shm.buf[:28]
            magic, channels, rate, buffer_frames, write_index, active = struct.unpack("iiiiqi", header_bytes)
        except Exception:
            return self._silence

        if magic != 0x41554449 or not active:
            return self._silence

        self.channels = channels
        self.rate = rate

        if self._silence.shape[1] != channels:
            self._silence = np.zeros((self.chunk_size, channels), dtype=np.float32)

        if self.last_read_index < 0 or write_index < self.last_read_index:
            self.last_read_index = max(0, write_index - self.chunk_size * 2)

        frames_available = write_index - self.last_read_index

        if frames_available == 0:
            if time.monotonic() - self._last_data_time >= SILENCE_TIMEOUT_SEC:
                return self._silence
            return None

        # Too far behind -> skip to latest
        if frames_available > buffer_frames:
            self.last_read_index = write_index - self.chunk_size * 4
            frames_available = write_index - self.last_read_index

        buffer_array = np.ndarray((buffer_frames, channels), dtype=np.float32, buffer=self.shm.buf[32:])
        start_idx = self.last_read_index % buffer_frames
        end_idx = start_idx + frames_available

        if end_idx <= buffer_frames:
            out_data = buffer_array[start_idx:end_idx, :].copy()
        else:
            first_part = buffer_frames - start_idx
            second_part = frames_available - first_part
            out_data = np.concatenate((buffer_array[start_idx:, :], buffer_array[:second_part, :]), axis=0)

        self.last_read_index = write_index
        self._last_data_time = time.monotonic()

        return out_data

    def close(self):
        if self.shm is not None:
            self.shm.close()

# For backwards compatibility with visualizer modules
AudioCapture = AudioCaptureClient