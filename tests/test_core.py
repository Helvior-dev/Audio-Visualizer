"""Offline checks for configuration, DSP and audio capture lifecycle."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from core import config_manager
from core.audio_capture import AudioCaptureEngine, AudioSource, KIND_MICROPHONE
from core.dsp import LoudnessProcessor


class ConfigTests(unittest.TestCase):
    def test_save_and_load_without_touching_user_appdata(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "config.json"
            with patch.object(config_manager, "CONFIG_DIR", root), patch.object(
                config_manager, "CONFIG_PATH", path
            ), patch.object(config_manager, "LOCAL_LEGACY_CONFIG", root / "absent.json"):
                config = config_manager.AppConfig()
                config.fps_limit = 60
                config.accent_color = "#FF4570"
                config.theme = "custom"
                config.floating_modules["spectrum"] = True
                config_manager.save_config(config)

                loaded = config_manager.load_config()
                self.assertEqual(loaded.fps_limit, 60)
                self.assertEqual(loaded.accent_color, "#FF4570")
                self.assertEqual(loaded.theme, "custom")
                self.assertTrue(loaded.floating_modules["spectrum"])
                self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["fps_limit"], 60)

                path.write_text("{invalid", encoding="utf-8")
                self.assertEqual(config_manager.load_config().fps_limit, 144)

                path.write_text(json.dumps({"accent_color": "#FF4570"}), encoding="utf-8")
                self.assertEqual(config_manager.load_config().theme, "custom")
                path.write_text(json.dumps({"accent_color": "#58A6FF"}), encoding="utf-8")
                self.assertEqual(config_manager.load_config().theme, "blue")
                self.assertEqual(config_manager.load_config().accent_color, "#91c5ff")


class DspTests(unittest.TestCase):
    def test_true_peak_finds_intersample_maximum_and_survives_chunk_boundaries(self):
        rate = 48000
        time = np.arange(rate, dtype=np.float64) / rate
        signal = np.sin(2 * np.pi * 12000 * time + np.pi / 4).astype(np.float32)
        sample_peak = 20 * np.log10(np.max(np.abs(signal)))
        readings = []
        for chunk_size in (rate // 10, rate):
            processor = LoudnessProcessor(rate)
            for pos in range(0, len(signal), chunk_size):
                chunk = signal[pos:pos + chunk_size]
                processor.process(chunk, chunk, len(chunk) / rate)
            readings.append(processor.true_peak_db)
            processor.reset_integrated()
            self.assertEqual(processor.true_peak_db, -70.0)

        self.assertLess(sample_peak, -2.9)
        self.assertGreater(readings[0], -1.0)
        self.assertAlmostEqual(readings[0], readings[1], delta=0.15)

    def test_true_peak_is_stable_across_irregular_splits_and_rates(self):
        for rate in (44100, 48000, 96000):
            with self.subTest(rate=rate):
                time = np.arange(rate) / rate
                signal = np.zeros(rate, dtype=np.float32)
                signal[:rate // 2] = np.sin(2 * np.pi * (rate / 4) * time[:rate // 2] + np.pi / 4)
                signal[rate // 2:] = 0.5 * np.sin(2 * np.pi * 1000 * time[rate // 2:])

                whole = LoudnessProcessor(rate)
                whole.process(signal, signal, 1.0)
                split = LoudnessProcessor(rate)
                offset = 0
                step = 0
                while offset < rate:
                    count = (1, 7, 1023, 128)[step % 4]
                    part = signal[offset:offset + count]
                    split.process(part, part, len(part) / rate)
                    offset += len(part)
                    step += 1
                self.assertAlmostEqual(whole.true_peak_db, split.true_peak_db, places=5)
                self.assertGreaterEqual(split.true_peak_db, 20 * np.log10(np.max(np.abs(signal))))

    def test_true_peak_matches_reference_signals_at_supported_rates(self):
        # FFmpeg 9.0.2 ebur128=peak=true, rounded to 0.1 dBFS.
        for rate in (44100, 48000, 96000):
            with self.subTest(rate=rate):
                time = np.arange(rate) / rate
                tone = np.sin(2 * np.pi * (rate / 4) * time + np.pi / 4)
                impulse = np.zeros(rate, dtype=np.float32)
                impulse[rate // 2] = 0.8
                for signal, expected in ((tone, 0.6),
                                         (tone * np.sin(np.pi * time) ** 2, 0.0),
                                         (impulse, -1.9)):
                    meter = LoudnessProcessor(rate)
                    for pos in range(0, rate, 1024):
                        chunk = signal[pos:pos + 1024].astype(np.float32)
                        meter.process(chunk, chunk, len(chunk) / rate)
                    self.assertAlmostEqual(meter.true_peak_db, expected, delta=0.2)

    def test_integrated_loudness_is_independent_of_callback_chunk_size(self):
        rate = 48000
        time = np.arange(4 * rate) / rate
        # Short pulses vanish if the processor repeats only the last 400 ms
        # of each one-second callback instead of collecting every gate window.
        signal = (np.where(time % 1.0 < 0.2, 0.25, 0.0)
                  * np.sin(2 * np.pi * 1000 * time)).astype(np.float32)

        readings = []
        for chunk_size in (rate // 10, rate):
            processor = LoudnessProcessor(rate)
            for pos in range(0, len(signal), chunk_size):
                chunk = signal[pos:pos + chunk_size]
                processor.process(chunk, chunk, len(chunk) / rate)
            readings.append(processor.integrated_lufs)

        self.assertGreater(readings[0], -70.0)
        self.assertAlmostEqual(readings[0], readings[1], delta=0.1)

    def test_doubling_sine_amplitude_adds_about_six_lufs(self):
        rate = 48000
        time = np.arange(rate, dtype=np.float32) / rate
        sine = np.sin(2 * np.pi * 1000 * time).astype(np.float32)

        readings = []
        for amplitude in (0.1, 0.2):
            processor = LoudnessProcessor(rate)
            for pos in range(0, len(sine), rate // 10):
                chunk = amplitude * sine[pos:pos + rate // 10]
                processor.process(chunk, chunk, len(chunk) / rate)
            readings.append(processor.integrated_lufs)

        self.assertAlmostEqual(readings[1] - readings[0], 6.0206, delta=0.1)

    def test_silence_and_signal_then_reset_integrated(self):
        rate = 48000
        processor = LoudnessProcessor(rate)
        silence = np.zeros(rate, dtype=np.float32)
        processor.process(silence, silence, 1.0)
        self.assertEqual(processor.momentary_lufs, -70.0)
        self.assertEqual(processor.true_peak_db, -70.0)

        time = np.arange(rate, dtype=np.float32) / rate
        signal = (0.25 * np.sin(2 * np.pi * 100 * time)).astype(np.float32)
        processor.process(signal, signal, 1.0)
        self.assertGreater(processor.momentary_lufs, -70.0)
        self.assertGreater(processor.integrated_lufs, -70.0)
        self.assertLessEqual(processor.peak_db, 0.0)
        processor.reset_integrated()
        self.assertEqual(processor.integrated_lufs, -70.0)
        self.assertEqual(processor.lra, 0.0)


class CaptureLifecycleTests(unittest.TestCase):
    def test_reader_recovers_after_full_wrap_and_source_change(self):
        callbacks = []
        pa = Mock()

        def open_stream(**kwargs):
            callbacks.append(kwargs["stream_callback"])
            return Mock()

        pa.open.side_effect = open_stream
        devices = iter((
            {"index": 1, "defaultSampleRate": 44100, "maxInputChannels": 2},
            {"index": 2, "defaultSampleRate": 96000, "maxInputChannels": 1},
        ))
        with patch("core.audio_capture.pyaudio.PyAudio", return_value=pa), patch(
            "core.audio_capture.shm.SharedMemory", side_effect=OSError("unavailable")
        ), patch.object(AudioCaptureEngine, "_resolve_device", side_effect=lambda _: next(devices)):
            engine = AudioCaptureEngine()
            try:
                reader = engine.create_reader()
                first = np.ones((engine.buffer_frames, 2), dtype=np.float32)
                callbacks[0](first.tobytes(), len(first), None, None)
                result = reader.read_chunk()
                self.assertIsNotNone(result)
                self.assertEqual(result[0][-1, 0], 1.0)

                engine.change_source(AudioSource(KIND_MICROPHONE, 2, "Test microphone"))
                self.assertIsNone(reader.read_chunk())
                self.assertEqual(engine.rate, 96000)
                self.assertEqual(engine.channels, 1)
                mono = np.full((engine.buffer_frames + 128, 1), 0.5, dtype=np.float32)
                callbacks[1](mono.tobytes(), len(mono), None, None)
                latest = reader.read_chunk()
                self.assertIsNotNone(latest)
                self.assertEqual(latest[1:], (96000, 1))
                self.assertTrue(np.all(latest[0] == 0.5))
                self.assertEqual(engine.get_latest_frames(40)[0].shape, (40, 2))

                more = (np.arange(engine.buffer_frames + 128, dtype=np.float32) / 100_000).reshape(-1, 1)
                callbacks[1](more.tobytes(), len(more), None, None)
                frames, rate, channels = engine.get_latest_frames(40)
                np.testing.assert_array_equal(frames[:, 0], more[-40:, 0])
                self.assertEqual((rate, channels), (96000, 1))
            finally:
                engine.close()

    def test_failed_stream_start_closes_opened_stream(self):
        pa = Mock()
        stream = Mock()
        stream.start_stream.side_effect = OSError("device disconnected")
        pa.open.return_value = stream
        with patch("core.audio_capture.pyaudio.PyAudio", return_value=pa), patch(
            "core.audio_capture.shm.SharedMemory", side_effect=OSError("unavailable")
        ), patch.object(AudioCaptureEngine, "_resolve_device", return_value={
            "index": 1, "defaultSampleRate": 48000, "maxInputChannels": 2,
        }):
            engine = AudioCaptureEngine()
            try:
                self.assertFalse(engine.is_running)
                self.assertIn("device disconnected", engine.last_error)
                stream.close.assert_called_once_with()
                self.assertIsNone(engine.stream)
            finally:
                engine.close()

    def test_change_source_closes_previous_stream_and_close_releases_resources(self):
        streams = []

        def open_stream(**kwargs):
            stream = Mock()
            streams.append(stream)
            return stream

        pa = Mock()
        pa.open.side_effect = open_stream
        memory = Mock()
        with patch("core.audio_capture.pyaudio.PyAudio", return_value=pa), patch(
            "core.audio_capture.shm.SharedMemory", return_value=memory
        ), patch.object(AudioCaptureEngine, "_resolve_device", return_value={
            "index": 1, "defaultSampleRate": 48000, "maxInputChannels": 2,
        }):
            engine = AudioCaptureEngine(source=AudioSource())
            try:
                self.assertTrue(engine.is_running)
                self.assertEqual(engine.rate, 48000)
                engine.change_source(AudioSource(KIND_MICROPHONE, 1, "Test microphone"))
                streams[0].stop_stream.assert_called_once_with()
                streams[0].close.assert_called_once_with()
                streams[1].start_stream.assert_called_once_with()
                self.assertEqual(engine.source.kind, KIND_MICROPHONE)
            finally:
                engine.close()
            streams[1].close.assert_called_once_with()
            pa.terminate.assert_called_once_with()

    def test_second_instance_does_not_attach_to_or_unlink_first_shared_block(self):
        pa = Mock()
        pa.open.return_value = Mock()
        with patch("core.audio_capture.pyaudio.PyAudio", return_value=pa), patch(
            "core.audio_capture.shm.SharedMemory", side_effect=FileExistsError
        ) as memory, patch.object(AudioCaptureEngine, "_resolve_device", return_value={
            "index": 1, "defaultSampleRate": 48000, "maxInputChannels": 2,
        }):
            engine = AudioCaptureEngine()
            try:
                self.assertIsNone(engine.shm)
                self.assertTrue(engine.is_running)
            finally:
                engine.close()
            memory.assert_called_once()
            pa.terminate.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
