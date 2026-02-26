"""Audio analysis for Neewer sound-reactive scenes.

Provides AudioFrame with amplitude, beat detection, and frequency bands.
Pluggable source abstraction — MicSource implemented, others planned.

Requires: pip install -r requirements-audio.txt (numpy, sounddevice)
"""
try:
    import numpy as np
except ImportError:
    raise ImportError("Audio requires numpy. Install: pip install -r requirements-audio.txt")

import asyncio


class AudioFrame:
    """Single frame of audio analysis results."""

    def __init__(self, amplitude=0.0, beat=False, bands=None, bpm=0.0):
        self.amplitude = amplitude
        self.beat = beat
        self.bands = bands or [0.0, 0.0, 0.0]
        self.bpm = bpm


def compute_rms(samples):
    """Compute RMS (root mean square) amplitude of a sample buffer."""
    if len(samples) == 0:
        return 0.0
    return float(np.sqrt(np.mean(samples ** 2)))


def compute_bands(samples, sample_rate=44100):
    """Split audio into bass/mid/treble frequency bands via FFT.

    Returns (bass, mid, treble) each normalized 0.0-1.0.
    Bass: <300Hz, Mid: 300-2000Hz, Treble: >2000Hz
    """
    n = len(samples)
    if n == 0:
        return 0.0, 0.0, 0.0

    fft = np.abs(np.fft.rfft(samples))
    freqs = np.fft.rfftfreq(n, 1.0 / sample_rate)

    bass_mask = freqs < 300
    mid_mask = (freqs >= 300) & (freqs < 2000)
    treble_mask = freqs >= 2000

    total = np.sum(fft) + 1e-10
    bass = float(np.sum(fft[bass_mask]) / total)
    mid = float(np.sum(fft[mid_mask]) / total)
    treble = float(np.sum(fft[treble_mask]) / total)

    return bass, mid, treble


class BeatDetector:
    """Energy-based beat/onset detection."""

    def __init__(self, threshold=1.5, history_size=20):
        self.threshold = threshold
        self.history = []
        self.history_size = history_size
        self.beat_times = []

    def process(self, samples):
        """Process a sample buffer. Returns True if beat detected."""
        energy = float(np.mean(samples ** 2))
        self.history.append(energy)
        if len(self.history) > self.history_size:
            self.history.pop(0)

        if len(self.history) < 3:
            return False

        avg = sum(self.history) / len(self.history)
        if avg < 1e-8:
            return False

        is_beat = energy > avg * self.threshold
        return is_beat

    @property
    def bpm(self):
        if len(self.beat_times) < 2:
            return 0.0
        intervals = [self.beat_times[i] - self.beat_times[i - 1]
                     for i in range(1, len(self.beat_times))]
        avg_interval = sum(intervals) / len(intervals)
        if avg_interval <= 0:
            return 0.0
        return 60.0 / avg_interval


class AudioSource:
    """Base class for audio sources."""

    async def start(self):
        raise NotImplementedError

    async def read_frame(self):
        raise NotImplementedError

    async def stop(self):
        raise NotImplementedError


class MicSource(AudioSource):
    """Microphone audio source via sounddevice."""

    def __init__(self, device=None, sample_rate=44100, block_size=2048):
        self.device = device
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.stream = None
        self.beat_detector = BeatDetector()
        self._buffer = None
        self._buffer_ready = None

    async def start(self):
        import sounddevice as sd
        self._buffer_ready = asyncio.Event()

        def callback(indata, frames, time_info, status):
            self._buffer = indata[:, 0].copy()
            try:
                self._buffer_ready.set()
            except RuntimeError:
                pass

        self.stream = sd.InputStream(
            device=self.device,
            samplerate=self.sample_rate,
            blocksize=self.block_size,
            channels=1,
            dtype="float32",
            callback=callback,
        )
        self.stream.start()

    async def read_frame(self):
        if self._buffer_ready is None:
            return AudioFrame()

        self._buffer_ready.clear()
        try:
            await asyncio.wait_for(self._buffer_ready.wait(), timeout=0.1)
        except asyncio.TimeoutError:
            return AudioFrame()

        samples = self._buffer
        if samples is None:
            return AudioFrame()

        amplitude = min(1.0, compute_rms(samples))
        beat = self.beat_detector.process(samples)
        bands = list(compute_bands(samples, self.sample_rate))

        if beat:
            import time
            self.beat_detector.beat_times.append(time.time())
            if len(self.beat_detector.beat_times) > 20:
                self.beat_detector.beat_times.pop(0)

        return AudioFrame(
            amplitude=amplitude,
            beat=beat,
            bands=bands,
            bpm=self.beat_detector.bpm,
        )

    async def stop(self):
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
