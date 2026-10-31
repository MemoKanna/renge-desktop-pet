from array import array
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import wave

ROOT = Path(__file__).resolve().parents[1]


def synthetic_wav(path):
    path.parent.mkdir(exist_ok=True, parents=True)
    with wave.open(str(path), 'wb') as out:
        out.setparams((1, 2, 22050, 0, 'NONE', 'not compressed'))
        out.writeframes(array('h', [1000, -1000] * 2205).tobytes())


@unittest.skipUnless(os.name == 'nt', 'Win32 interaction and audio checks require Windows')
class WindowsChecks(unittest.TestCase):
    def test_custom_voice_import_and_invalid_file_rejection(self):
        from voice import VoiceLibrary
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            synthetic_wav(base / 'voices/飞扑-test.wav')
            (base / 'voices/摸头-invalid.wav').write_bytes(b'invalid')
            library = VoiceLibrary(ROOT, base)
            self.assertEqual(len(library.clips), 1)
            self.assertEqual(library.choose('pounce').id, 'custom-飞扑-test')
            self.assertIsNone(library.choose('pet'))

    def test_volume_preserves_duration_and_bounds(self):
        from voice import WaveOutput
        values = array('h', [-30000, -1000, 0, 1000, 30000])
        result = WaveOutput.scaled_pcm(values.tobytes(), 25)
        self.assertEqual(list(array('h', result)), [-7500, -250, 0, 250, 7500])
        self.assertEqual(len(result), len(values.tobytes()))

    def test_cancel_during_device_open_does_not_block_animation_thread(self):
        from voice import VoiceClip, VoicePlayer
        opened = threading.Event()
        release = threading.Event()
        played = []

        class SlowOutput:
            def __init__(self):
                self.handle = None
                self.starts = self.completions = 0
                self.last_clip = None
                self.last_error = ''
            def play(self, clip, volume, cancelled):
                opened.set()
                release.wait(2)
                if not cancelled():
                    played.append(clip.id)
            def stop(self):
                self.handle = None
            def poll(self):
                pass

        with patch('voice.WaveOutput', SlowOutput):
            player = VoicePlayer()
            started = time.perf_counter()
            player.play(VoiceClip('test', Path('unused'), (), '', .2), 50)
            self.assertLess(time.perf_counter() - started, .2)
            self.assertTrue(opened.wait(2))
            player.stop()
            release.set()
            player.close(wait=True)
            self.assertEqual(played, [])

    def test_pounce_voice_fires_once_and_pending_is_cancelled(self):
        from renge_pet import Pet
        from voice import VoiceLibrary
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            synthetic_wav(base / 'voices/飞扑-test.wav')
            settings = base / 'settings.json'
            settings.write_text(json.dumps({'voice_enabled': True, 'quiet': True}), encoding='utf-8')
            pet = Pet(argparse.Namespace(settings_file=str(settings), track='field', diagnostics=None, exit_after=0, start_state='idle'))
            pet.voice_player.close(wait=True)
            pet.voices = VoiceLibrary(ROOT, base)

            class Player:
                def __init__(self):
                    self.calls = []
                    self.stops = 0
                def play(self, clip, volume):
                    self.calls.append(clip.id)
                    return True
                def stop(self):
                    self.stops += 1

            pet.voice_player = Player()
            pet.hwnd = 1
            pet.start_pounce()
            pet.motion.age = .29
            pet.pounce_events(time.monotonic())
            self.assertEqual(pet.voice_player.calls, [])
            pet.motion.age = .31
            pet.pounce_events(time.monotonic())
            self.assertEqual(pet.voice_player.calls, ['custom-飞扑-test'])
            stops = pet.voice_player.stops
            pet.start_pounce()
            pet.motion.age = .6
            pet.pounce_events(time.monotonic())
            self.assertEqual(len(pet.voice_player.calls), 1)
            self.assertEqual(pet.voice_player.stops, stops)
            pet.motion.enter('idle')
            pet.start_pounce()
            pet.interrupt_music()
            pet.motion.age = .5
            pet.pounce_events(time.monotonic())
            self.assertEqual(len(pet.voice_player.calls), 1)

    def test_native_window_lifecycle_without_optional_voice_pack(self):
        # Exercise the actual message loop, rendering and exit path. Settings
        # are isolated; the application never needs audio hardware for this test.
        for mode, duration in [('idle', 1.5), ('pounce', 6.4), ('flute', 1.6)]:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                base = Path(folder)
                settings = base / 'settings.json'
                diagnostics = base / 'diagnostics.json'
                settings.write_text(json.dumps({'size': 160, 'sound': False, 'voice_enabled': False, 'quiet': True}), encoding='utf-8')
                subprocess.run([sys.executable, str(ROOT / 'renge_pet.py'), '--settings-file', str(settings),
                                '--diagnostics', str(diagnostics), '--start-state', mode, '--track', 'field',
                                '--exit-after', str(duration)], cwd=ROOT, timeout=45, check=True)
                state = json.loads(diagnostics.read_text(encoding='utf-8'))
                self.assertEqual(state['voice_count'], 0)
                self.assertEqual(state['music_count'], 3)
                self.assertEqual(state['voice_error'], '')
                self.assertGreater(state['frames'], 5)
                self.assertFalse(state['voice_playing'])
                if mode == 'pounce':
                    self.assertEqual(state['state'], 'idle')
