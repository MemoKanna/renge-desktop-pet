import json
import math
from pathlib import Path
import unittest
import wave

from action_rig import ActionRig, UPPER_ARM, FOREARM, POUNCE_DURATION
from activities import Activities
from motion import Motion
from sprites import Sprites
from walk_rig import WalkRig

ROOT = Path(__file__).resolve().parents[1]


class CoreChecks(unittest.TestCase):
    def test_flight_distance_is_independent_of_frame_rate(self):
        distances = []
        for fps in (30, 60, 120):
            motion = Motion(size=200)
            motion.pounce(-1)
            total = sum(motion.update(1 / fps) for _ in range(round(POUNCE_DURATION * fps) + 2))
            self.assertEqual(motion.state, 'idle')
            distances.append(total)
        for distance in distances:
            self.assertAlmostEqual(distance, -140, places=7)

    def test_flute_stops_audio_when_interrupted(self):
        motion = Motion()
        motion.flute()
        for _ in range(40):
            motion.update(.02)
        self.assertEqual(motion.state, 'flute_play')
        self.assertIn('audio_start', motion.events)
        motion.pounce()
        self.assertIn('audio_stop', motion.events)

    def test_flight_arm_bones_remain_connected_and_continuous(self):
        actor = ActionRig(ROOT / 'assets', WalkRig(ROOT / 'assets'))
        previous = None
        maximum_step = 0
        for i in range(697):
            arms = actor.configuration('pounce', i / 120)['arms']
            for side, (a, b, c) in arms.items():
                self.assertAlmostEqual(math.dist(a, b), UPPER_ARM, places=8)
                self.assertAlmostEqual(math.dist(b, c), FOREARM, places=8)
                if previous:
                    maximum_step = max(maximum_step, *(math.dist(p, q) for p, q in zip((a, b, c), previous[side])))
            previous = arms
        self.assertLess(maximum_step, 8)

    def test_delayed_reminder_waits_until_available(self):
        activity = Activities()
        activity.reminder(25, 100)
        self.assertFalse(activity.poll(1700, False))
        self.assertTrue(activity.poll(1700, True))
        self.assertFalse(activity.poll(1701, True))

    def test_guessing_game_consumes_one_selection(self):
        activity = Activities(game_open=True, opponent=0)
        self.assertEqual(activity.choose(2), (0, 'win'))
        self.assertIsNone(activity.choose(2))


class PublicAssetChecks(unittest.TestCase):
    def test_every_action_renders_without_external_files(self):
        sprites = Sprites(ROOT / 'assets')
        for pose in [('base', 0, 0, 0., False), ('walk', 2, 3, .4, False),
                     ('flute', 3, 4, .5, False), ('pounce', 0, 0, .8, False),
                     ('pet', 0, 0, 1., False), ('emote', 1, 0, 1., False)]:
            with self.subTest(pose=pose):
                image = sprites.sample(pose, 200)
                self.assertIsNotNone(image.getchannel('A').getbbox())
                self.assertEqual(image.mode, 'RGBA')

    def test_public_distribution_has_no_bundled_original_recordings(self):
        folder = ROOT / 'assets' / 'voice'
        manifest = json.loads((folder / 'clips.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['clips'], [])
        self.assertEqual(list(folder.glob('*.wav')), [])
        tracks = json.loads((ROOT / 'assets/music/tracks.json').read_text(encoding='utf-8'))
        self.assertEqual({t['id'] for t in tracks}, {'star', 'brother', 'field'})
        self.assertEqual({p.name for p in (ROOT / 'assets/music').glob('*.wav')}, {t['file'] for t in tracks})
        for track in tracks:
            with wave.open(str(ROOT / 'assets/music' / track['file']), 'rb') as audio:
                self.assertEqual(audio.getsampwidth(), 2)
                self.assertGreater(audio.getnframes(), 1000)
