"""
Digital Signal Processing (DSP) Module.
Contains real-time audio analysis algorithms:
- ITU-R BS.1770-4 / EBU R128 K-weighting loudness (LUFS M/S/INT/LRA/Peak)
- Logarithmic FFT spectrum calculation with smoothing and musical note conversion
- Oscilloscope waveform triggering (zero-crossing / correlation)
- Vectorscope (Lissajous Mid/Side + Phase correlation)
"""

import numpy as np
from typing import Tuple, List, Optional

DB_MIN = -70.0
DB_MAX = 0.0


# -----------------------------------------------------------------------------
# 1. K-Weighting & Loudness Calculation (EBU R128 / ITU-R BS.1770-4)
# -----------------------------------------------------------------------------

def _high_shelf_coeffs(fs: float, f0: float = 1681.9744509555319, gain_db: float = 3.99984385397, q: float = 0.7071752369554193):
    A = 10 ** (gain_db / 40.0)
    w0 = 2 * np.pi * f0 / fs
    alpha = np.sin(w0) / (2 * q)
    cos_w0 = np.cos(w0)
    sqrt_a = np.sqrt(A)

    b0 = A * ((A + 1) + (A - 1) * cos_w0 + 2 * sqrt_a * alpha)
    b1 = -2 * A * ((A - 1) + (A + 1) * cos_w0)
    b2 = A * ((A + 1) + (A - 1) * cos_w0 - 2 * sqrt_a * alpha)
    a0 = (A + 1) - (A - 1) * cos_w0 + 2 * sqrt_a * alpha
    a1 = 2 * ((A - 1) - (A + 1) * cos_w0)
    a2 = (A + 1) - (A - 1) * cos_w0 - 2 * sqrt_a * alpha
    return b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0


def _high_pass_coeffs(fs: float, f0: float = 38.13547087613982, q: float = 0.5003270373253953):
    w0 = 2 * np.pi * f0 / fs
    alpha = np.sin(w0) / (2 * q)
    cos_w0 = np.cos(w0)

    b0 = (1 + cos_w0) / 2
    b1 = -(1 + cos_w0)
    b2 = (1 + cos_w0) / 2
    a0 = 1 + alpha
    a1 = -2 * cos_w0
    a2 = 1 - alpha
    return b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0


try:
    from scipy.signal import lfilter
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False


class BiquadFilter:
    """Hardware fast biquad filter with persistent filter state."""
    def __init__(self, b0, b1, b2, a1, a2):
        self.b = np.array([b0, b1, b2], dtype=np.float64)
        self.a = np.array([1.0, a1, a2], dtype=np.float64)
        self.zi = np.zeros(2, dtype=np.float64)
        self.b0, self.b1, self.b2, self.a1, self.a2 = b0, b1, b2, a1, a2
        self.z1 = 0.0
        self.z2 = 0.0

    def process(self, x: np.ndarray) -> np.ndarray:
        if len(x) == 0:
            return x
        if HAS_SCIPY:
            y, self.zi = lfilter(self.b, self.a, x, zi=self.zi)
            return y.astype(np.float32)
        else:
            y = np.empty_like(x)
            b0, b1, b2, a1, a2 = self.b0, self.b1, self.b2, self.a1, self.a2
            z1, z2 = self.z1, self.z2
            for i in range(len(x)):
                xi = x[i]
                yi = b0 * xi + z1
                z1 = b1 * xi - a1 * yi + z2
                z2 = b2 * xi - a2 * yi
                y[i] = yi
            self.z1, self.z2 = z1, z2
            return y


class KWeightingFilter:
    """Pre-filter (high shelf) -> RLB filter (high-pass), per BS.1770-4."""
    def __init__(self, sample_rate: float):
        self.sample_rate = sample_rate
        b0, b1, b2, a1, a2 = _high_shelf_coeffs(sample_rate)
        self.stage1 = BiquadFilter(b0, b1, b2, a1, a2)
        b0, b1, b2, a1, a2 = _high_pass_coeffs(sample_rate)
        self.stage2 = BiquadFilter(b0, b1, b2, a1, a2)

    def process(self, x: np.ndarray) -> np.ndarray:
        return self.stage2.process(self.stage1.process(x))


class LoudnessProcessor:
    """Computes Momentary, Short-Term, Integrated LUFS, LRA and True-Peak."""
    ABS_GATE_LUFS = -70.0
    REL_GATE_LU = -10.0
    LRA_REL_GATE_LU = -20.0
    LRA_LOW_PCT = 10.0
    LRA_HIGH_PCT = 95.0
    PEAK_DECAY_DB_PER_SEC = 11.0

    def __init__(self, sample_rate: int = 44100):
        self.sample_rate = sample_rate
        self.kw_l = KWeightingFilter(sample_rate)
        self.kw_r = KWeightingFilter(sample_rate)

        self.momentary_samples = max(1, int(round(0.4 * sample_rate)))
        self.gating_block_samples = max(1, int(round(0.4 * sample_rate)))
        self.shortterm_samples = max(1, int(round(3.0 * sample_rate)))

        self._buf_sq = np.zeros(self.shortterm_samples, dtype=np.float64)
        self._filled = 0

        self._block_hop_samples = max(1, int(round(0.1 * sample_rate)))
        self._samples_since_block = 0
        self._integrated_blocks: List[float] = []

        self._st_hop_samples = max(1, int(round(1.0 * sample_rate)))
        self._samples_since_st = 0
        self._st_history: List[float] = []

        self.momentary_lufs = self.ABS_GATE_LUFS
        self.shortterm_lufs = self.ABS_GATE_LUFS
        self.integrated_lufs = self.ABS_GATE_LUFS
        self.lra = 0.0
        self.peak_db = self.ABS_GATE_LUFS
        self._peak_hold_db = self.ABS_GATE_LUFS

    def reset_integrated(self):
        self._integrated_blocks.clear()
        self._st_history.clear()
        self.integrated_lufs = self.ABS_GATE_LUFS
        self.lra = 0.0

    @staticmethod
    def _power_to_lufs(mean_square: float) -> float:
        if mean_square <= 1e-12:
            return -70.0
        return float(-0.691 + 10.0 * np.log10(mean_square))

    def process(self, left: np.ndarray, right: np.ndarray, dt: float):
        if len(left) == 0:
            return

        chunk_peak = float(np.max(np.abs(np.concatenate([left, right]))))
        chunk_peak_db = 20.0 * np.log10(max(chunk_peak, 1e-10))
        if chunk_peak_db > self._peak_hold_db:
            self._peak_hold_db = chunk_peak_db
        else:
            self._peak_hold_db = max(chunk_peak_db, self._peak_hold_db - self.PEAK_DECAY_DB_PER_SEC * dt)
        self.peak_db = self._peak_hold_db

        kl = self.kw_l.process(left.astype(np.float64))
        kr = self.kw_r.process(right.astype(np.float64))
        sq = kl * kl + kr * kr

        n = len(sq)
        if n >= self.shortterm_samples:
            self._buf_sq[:] = sq[-self.shortterm_samples:]
            self._filled = self.shortterm_samples
        else:
            self._buf_sq = np.roll(self._buf_sq, -n)
            self._buf_sq[-n:] = sq
            self._filled = min(self.shortterm_samples, self._filled + n)

        m_n = min(self.momentary_samples, self._filled)
        if m_n > 0:
            self.momentary_lufs = self._power_to_lufs(self._buf_sq[-m_n:].mean())

        if self._filled > 0:
            tail = self._buf_sq if self._filled >= self.shortterm_samples else self._buf_sq[-self._filled:]
            self.shortterm_lufs = self._power_to_lufs(tail.mean())

        self._samples_since_block += n
        new_block = False
        while self._filled >= self.gating_block_samples and self._samples_since_block >= self._block_hop_samples:
            self._samples_since_block -= self._block_hop_samples
            self._integrated_blocks.append(float(self._buf_sq[-self.gating_block_samples:].mean()))
            new_block = True
            if len(self._integrated_blocks) > 10_000:
                self._integrated_blocks = self._integrated_blocks[-5_000:]

        if new_block:
            self.integrated_lufs = self._compute_integrated()

        self._samples_since_st += n
        if self._samples_since_st >= self._st_hop_samples:
            self._samples_since_st = 0
            self._st_history.append(self.shortterm_lufs)
            if len(self._st_history) > 2_000:
                self._st_history = self._st_history[-1_000:]
            self.lra = self._compute_lra()

    def _compute_integrated(self) -> float:
        if not self._integrated_blocks:
            return -70.0
        blocks = np.array(self._integrated_blocks)
        loudness = -0.691 + 10.0 * np.log10(np.maximum(blocks, 1e-12))
        gated = blocks[loudness > self.ABS_GATE_LUFS]
        if len(gated) == 0:
            return -70.0
        mean_gated = float(gated.mean())
        rel_threshold = self._power_to_lufs(mean_gated) + self.REL_GATE_LU
        gated_loudness = -0.691 + 10.0 * np.log10(np.maximum(gated, 1e-12))
        gated2 = gated[gated_loudness > rel_threshold]
        if len(gated2) == 0:
            return self._power_to_lufs(mean_gated)
        return self._power_to_lufs(float(gated2.mean()))

    def _compute_lra(self) -> float:
        if len(self._st_history) < 2:
            return 0.0
        values = np.array(self._st_history)
        values = values[values > self.ABS_GATE_LUFS]
        if len(values) < 2:
            return 0.0
        mean_power = np.mean(10 ** ((values + 0.691) / 10.0))
        rel_gate = self._power_to_lufs(float(mean_power)) + self.LRA_REL_GATE_LU
        gated = values[values > rel_gate]
        if len(gated) < 2:
            return 0.0
        lo = float(np.percentile(gated, self.LRA_LOW_PCT))
        hi = float(np.percentile(gated, self.LRA_HIGH_PCT))
        return max(0.0, hi - lo)


# -----------------------------------------------------------------------------
# 2. FFT Spectrum Analysis & Log Binning
# -----------------------------------------------------------------------------

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

def freq_to_note(freq_hz: float) -> Tuple[str, float]:
    """Convert frequency in Hz to musical note name (e.g., 'A4') and cents offset."""
    if freq_hz <= 0:
        return "---", 0.0
    midi = 69 + 12 * np.log2(freq_hz / 440.0)
    midi_round = int(round(midi))
    cents = (midi - midi_round) * 100
    octave = (midi_round // 12) - 1
    note_name = NOTE_NAMES[midi_round % 12]
    return f"{note_name}{octave}", float(cents)


class SpectrumProcessor:
    """FFT spectrum analyzer with logarithmic frequency mapping and peak-hold."""
    def __init__(self, num_bars: int = 320, min_freq: float = 20.0, max_freq: float = 20000.0, fft_size: int = 4096):
        self.num_bars = num_bars
        self.min_freq = min_freq
        self.max_freq = max_freq
        self.fft_size = fft_size

        self.window = np.blackman(fft_size).astype(np.float32)
        self.bar_freqs = np.geomspace(min_freq, max_freq, num_bars).astype(np.float32)
        
        self.smooth_bars = np.full(num_bars, DB_MIN, dtype=np.float32)
        self.peak_bars = np.full(num_bars, DB_MIN, dtype=np.float32)
        self.peak_hold_timer = np.zeros(num_bars, dtype=np.float32)

    def process(self, samples: np.ndarray, sample_rate: int, smoothing: float = 0.65, dt: float = 0.016, peak_hold_sec: float = 0.12):
        if len(samples) < self.fft_size:
            pad = np.zeros(self.fft_size - len(samples), dtype=np.float32)
            samples = np.concatenate([pad, samples])
        else:
            samples = samples[-self.fft_size:]

        # Windowed FFT
        windowed = samples * self.window
        fft_complex = np.fft.rfft(windowed)
        magnitudes = np.abs(fft_complex) / (self.fft_size / 2.0)
        magnitudes = np.maximum(magnitudes, 1e-7)
        db_spectrum = 20.0 * np.log10(magnitudes)

        fft_freqs = np.fft.rfftfreq(self.fft_size, 1.0 / sample_rate)

        # Logarithmic bin interpolation
        indices = np.searchsorted(fft_freqs, self.bar_freqs)
        indices = np.clip(indices, 0, len(db_spectrum) - 1)
        raw_bars = db_spectrum[indices]

        # Temporal smoothing
        self.smooth_bars = self.smooth_bars * smoothing + raw_bars * (1.0 - smoothing)
        self.smooth_bars = np.clip(self.smooth_bars, DB_MIN, DB_MAX)

        # Vectorized Peak hold & decay
        rising = self.smooth_bars >= self.peak_bars
        self.peak_bars[rising] = self.smooth_bars[rising]
        self.peak_hold_timer[rising] = peak_hold_sec

        falling = ~rising
        holding = falling & (self.peak_hold_timer > 0)
        self.peak_hold_timer[holding] -= dt

        decaying = falling & (self.peak_hold_timer <= 0)
        self.peak_bars[decaying] = np.maximum(DB_MIN, self.peak_bars[decaying] - 100.0 * dt)

        return self.smooth_bars, self.peak_bars


# -----------------------------------------------------------------------------
# 3. Oscilloscope Triggering
# -----------------------------------------------------------------------------

def find_waveform_trigger(samples: np.ndarray, target_length: int = 1024) -> np.ndarray:
    """
    Finds zero-crossing rising-edge trigger point for a stable oscilloscope view.
    """
    n = len(samples)
    if n <= target_length:
        if n < target_length:
            return np.pad(samples, (target_length - n, 0))
        return samples

    # Search for positive zero-crossing in the first 25% of the buffer
    search_limit = min(n - target_length, target_length)
    if search_limit <= 0:
        return samples[-target_length:]

    search_region = samples[:search_limit + 1]
    crossings = np.where((search_region[:-1] <= 0) & (search_region[1:] > 0))[0]

    if len(crossings) > 0:
        # Pick the crossing with the steepest slope
        slopes = search_region[crossings + 1] - search_region[crossings]
        best_crossing = crossings[np.argmax(slopes)]
        return samples[best_crossing:best_crossing + target_length]

    return samples[-target_length:]


# -----------------------------------------------------------------------------
# 4. Vectorscope & Phase Correlation
# -----------------------------------------------------------------------------

def compute_vectorscope_points(left: np.ndarray, right: np.ndarray, num_points: int = 1024) -> Tuple[np.ndarray, np.ndarray]:
    """
    Rotates stereo samples 45 degrees into Lissajous Mid/Side coordinate space.
    Mid = (L + R) / sqrt(2), Side = (L - R) / sqrt(2)
    """
    if len(left) < num_points:
        l_tail = left
        r_tail = right
    else:
        l_tail = left[-num_points:]
        r_tail = right[-num_points:]

    inv_sqrt2 = 0.7071067811865475
    # X = Side (L - R), Y = Mid (L + R)
    x = (l_tail - r_tail) * inv_sqrt2
    y = (l_tail + r_tail) * inv_sqrt2
    return x, y


def compute_stereo_correlation(left: np.ndarray, right: np.ndarray) -> float:
    """Computes Pearson phase correlation [-1.0 ... +1.0] between L and R channels."""
    if len(left) < 16:
        return 1.0
    dot_lr = np.sum(left * right)
    norm_l = np.sqrt(np.sum(left * left))
    norm_r = np.sqrt(np.sum(right * right))
    denom = norm_l * norm_r
    if denom < 1e-8:
        return 1.0
    corr = dot_lr / denom
    return float(np.clip(corr, -1.0, 1.0))
