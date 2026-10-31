"""Registered sprites and continuous animation on a stable transparent canvas.

Actual character bounds replace an assumed equal atlas grid. Face and sole
anchors keep hairstyle width/antenna height from moving the whole character.
"""
from pathlib import Path
from functools import lru_cache
import json
from statistics import median
from PIL import Image, ImageDraw, ImageFilter, ImageOps
from walk_rig import WalkRig
from action_rig import ActionRig

CANVAS = (600, 560)
FACE = (300, 230)
SOLE = 540
DESIGN_HEIGHT = 500


def smoothstep(value):
    value = max(0., min(1., value))
    return value * value * (3. - 2. * value)


class Sprites:
    def __init__(self, directory):
        directory = Path(directory)
        layout = json.loads((directory / 'layout.json').read_text(encoding='utf-8'))
        self.frames = {}
        self.metadata = {}
        for name in ('base', 'walk', 'flute'):
            with Image.open(directory / f'{name}.png') as source:
                sheet = source.convert('RGBA')
            if sheet.getchannel('A').getextrema()[0] != 0:
                raise ValueError(f'{name}: sprite atlas needs transparency')
            entries = layout[name]
            vertical = []
            for entry in entries:
                left, top, right, bottom = entry['face']
                height = entry['box'][3] - entry['box'][1]
                vertical.append((SOLE - FACE[1]) / (height - (top + bottom) / 2))
            target_width = median(e['face'][2] - e['face'][0] for e in entries) * median(vertical)
            frames, transforms = [], []
            for entry, sy in zip(entries, vertical):
                image = sheet.crop(entry['box'])
                left, top, right, bottom = entry['face']
                cx, cy = (left + right) / 2, (top + bottom) / 2
                sx = target_width / (right - left)
                transform = (1 / sx, 0, cx - FACE[0] / sx,
                             0, 1 / sy, cy - FACE[1] / sy)
                registered = image.transform(CANVAS, Image.Transform.AFFINE, transform,
                                             Image.Resampling.BICUBIC)
                frames.append(registered)
                transforms.append({'sx': sx, 'sy': sy, 'face': FACE, 'sole': SOLE})
            self.frames[name] = frames
            self.metadata[name] = {'sheet': sheet.size, 'boxes': [e['box'] for e in entries],
                                   'transforms': transforms}

        # Share the complete head/hair/legs throughout the playing cycle.
        # Only central fingers and mouthpiece vary; hairstyle cannot flicker.
        canonical = self.frames['flute'][3]
        mask = Image.new('L', CANVAS)
        ImageDraw.Draw(mask).polygon(((276, 266), (324, 266), (329, 302), (365, 319),
                                      (370, 406), (230, 406), (235, 319), (271, 302)), fill=255)
        mask = mask.filter(ImageFilter.GaussianBlur(2))
        self.flute_mask = mask
        for index in (2, 4, 5, 6):
            self.frames['flute'][index] = Image.composite(self.frames['flute'][index], canonical, mask)
        self.walk_rig = WalkRig(directory)
        self.actions = ActionRig(directory,self.walk_rig)
        # Blink only the two eye interiors. Every hair/body/face-outline pixel
        # remains from the open-eye pose, with its exact original alpha.
        mask=Image.new('L',CANVAS);d=ImageDraw.Draw(mask)
        d.rounded_rectangle((241,214,282,247),radius=8,fill=255)
        d.rounded_rectangle((319,214,360,247),radius=8,fill=255)
        self.blink_mask=mask.filter(ImageFilter.GaussianBlur(.8))

    @lru_cache(maxsize=96)
    def blink(self,closure,size,mirror=False):
        original=self.frames['base'][0]
        mixed=Image.blend(original,self.frames['base'][2],max(0.,min(1.,closure)))
        image=Image.composite(mixed,original,self.blink_mask)
        image.putalpha(original.getchannel('A'))
        image=image.resize(tuple(round(v*size/DESIGN_HEIGHT) for v in CANVAS),Image.Resampling.LANCZOS)
        return ImageOps.mirror(image) if mirror else image

    @staticmethod
    def foot(size):
        return SOLE * size / DESIGN_HEIGHT

    @lru_cache(maxsize=160)
    def pose(self, atlas, index, size, mirror=False):
        if atlas == 'walk':
            return self.walk_rig.render(index / 8, size, mirror)
        sprite = self.frames[atlas][index]
        dimensions = tuple(round(v * size / DESIGN_HEIGHT) for v in CANVAS)
        sprite = sprite.resize(dimensions, Image.Resampling.LANCZOS)
        return ImageOps.mirror(sprite) if mirror else sprite

    @lru_cache(maxsize=120)
    def premultiplied(self, atlas, index, size, mirror=False):
        return self.pose(atlas, index, size, mirror).convert('RGBa')

    def sample(self, pose, size):
        atlas, first, second, weight, mirror = pose
        if atlas=='blink':return self.blink(round(weight*48)/48,size,mirror)
        if atlas in ('pet','emote','pounce'):
            return self.actions.render(atlas,weight,size,first,mirror)
        if atlas == 'walk':
            return self.walk_rig.render((first + weight) / 8, size, mirror)
        if first == second or weight <= .0001:
            return self.pose(atlas, first, size, mirror)
        if weight >= .9999:
            return self.pose(atlas, second, size, mirror)
        return Image.blend(self.premultiplied(atlas, first, size, mirror),
                           self.premultiplied(atlas, second, size, mirror),
                           smoothstep(weight)).convert('RGBA')


class PoseMixer:
    """An interrupted transition starts from the displayed pose, not a key."""
    def __init__(self):
        self.state = None
        self.current = None
        self.previous = None
        self.changed_at = 0.
        self.duration = .18

    def reset(self):
        self.state = self.current = self.previous = None

    def render(self, sprites, pose, state, now, size):
        target = sprites.sample(pose, size)
        if self.state != state:
            self.previous = self.current
            self.changed_at = now
            self.state = state
        progress = (now - self.changed_at) / self.duration
        if self.previous is not None and self.previous.size == target.size and progress < 1:
            target = Image.blend(self.previous.convert('RGBa'), target.convert('RGBa'),
                                 smoothstep(progress)).convert('RGBA')
        else:
            self.previous = None
        self.current = target
        return target
