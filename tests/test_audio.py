"""Tests for neewer_audio.py — audio analysis."""
import numpy as np
from neewer import audio as neewer_audio


def test_audio_frame_defaults():
    frame = neewer_audio.AudioFrame()
    assert frame.amplitude == 0.0
    assert frame.beat is False
    assert frame.bands == [0.0, 0.0, 0.0]
    assert frame.bpm == 0.0


def test_rms():
    # Sine wave at full amplitude
    samples = np.sin(np.linspace(0, 2 * np.pi, 1024)).astype(np.float32)
    rms = neewer_audio.compute_rms(samples)
    assert 0.6 < rms < 0.8  # RMS of sine ~ 0.707


def test_rms_silence():
    samples = np.zeros(1024, dtype=np.float32)
    rms = neewer_audio.compute_rms(samples)
    assert rms == 0.0


def test_frequency_bands():
    sr = 44100
    # Pure 100Hz tone (bass)
    t = np.linspace(0, 2048 / sr, 2048, endpoint=False)
    tone = np.sin(2 * np.pi * 100 * t).astype(np.float32)
    bass, mid, treble = neewer_audio.compute_bands(tone, sr)
    assert bass > mid
    assert bass > treble


def test_frequency_bands_treble():
    sr = 44100
    # Pure 5000Hz tone (treble)
    t = np.linspace(0, 2048 / sr, 2048, endpoint=False)
    tone = np.sin(2 * np.pi * 5000 * t).astype(np.float32)
    bass, mid, treble = neewer_audio.compute_bands(tone, sr)
    assert treble > bass


def test_beat_detector_no_beat_on_silence():
    det = neewer_audio.BeatDetector()
    samples = np.zeros(2048, dtype=np.float32)
    for _ in range(10):
        assert det.process(samples) is False


def test_beat_detector_detects_onset():
    det = neewer_audio.BeatDetector()
    silence = np.zeros(2048, dtype=np.float32)
    # Prime with silence
    for _ in range(5):
        det.process(silence)
    # Sudden loud burst
    burst = np.ones(2048, dtype=np.float32) * 0.8
    result = det.process(burst)
    assert result is True
