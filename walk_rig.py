"""A continuous, planted-foot cutout walk. Artwork is generated separately;
this module only articulates its reusable character textures at runtime."""
from dataclasses import dataclass
from functools import lru_cache
import json
import math
from statistics import median
from pathlib import Path
from PIL import Image, ImageOps, ImageChops

CANVAS = (600, 560)
STRIDE = 140.0
GROUND = 540.0
ANKLE = 519.0
THIGH = SHIN = 49.0
THIGH_WIDTH = 44.0
SHIN_WIDTH = 36.0
CYCLE_VERSION = 'continuous-limbs-4.2-width44-36'


@dataclass(frozen=True)
class Foot:
    x: float
    y: float
    angle: float
    planted: bool


def foot_path(phase, root_x):
    t = phase % 1.
    if t < .5:
        return Foot(root_x + STRIDE / 4 - STRIDE * t, ANKLE, 0., True)
    u = (t - .5) * 2
    # Hermite endpoints share the stance velocity, so lifting/contact do not
    # reverse the foot abruptly. The swing leg advances while clearing ground.
    h01 = -2 * u ** 3 + 3 * u ** 2
    h10 = u ** 3 - 2 * u ** 2 + u
    h11 = u ** 3 - u ** 2
    x = -STRIDE / 4 + STRIDE / 2 * h01 - STRIDE / 2 * (h10 + h11)
    lift = 28 * math.sin(math.pi * u) ** 1.4
    angle = -18 * math.sin(2 * math.pi * u) * math.sin(math.pi * u)
    radians = math.radians(angle)
    bottom = max(-math.sin(radians) * sx + math.cos(radians) * sy
                 for sx in (-16., 36.) for sy in (-8., 21.))
    y = min(ANKLE - lift, GROUND - bottom)
    return Foot(root_x + x, y, angle, False)


def knee(hip, ankle):
    dx, dy = ankle[0] - hip[0], ankle[1] - hip[1]
    distance = math.hypot(dx, dy)
    if distance > THIGH + SHIN + 1e-6:
        raise ValueError('Unreachable walk pose')
    along = (THIGH ** 2 - SHIN ** 2 + distance ** 2) / (2 * distance)
    bend = math.sqrt(max(0., THIGH ** 2 - along ** 2))
    return (hip[0] + dx / distance * along + dy / distance * bend,
            hip[1] + dy / distance * along - dx / distance * bend)


def skeleton(phase):
    phase %= 1.
    wave = math.tau * phase
    bob = -6 * math.sin(wave) ** 2
    sway = .7 * math.sin(wave)
    legs = {}
    for name, offset, root_x in (('far', .5, 291.), ('near', 0., 274.)):
        foot = foot_path(phase + offset, root_x)
        hip = (root_x + sway, 429. + bob)
        ankle = (foot.x, foot.y)
        legs[name] = {'hip': hip, 'knee': knee(hip, ankle), 'ankle': ankle, 'foot': foot}
    arms = {}
    for name, sign, sx in (('far', 1., 321.), ('near', -1., 246.)):
        shoulder = (sx + sway, 310. + bob)
        angle = math.radians(sign * 14 * math.cos(wave))
        elbow = (shoulder[0] + math.sin(angle) * 59, shoulder[1] + math.cos(angle) * 59)
        forearm = angle + math.radians(5 + 3 * math.sin(wave + sign))
        hand = (elbow[0] + math.sin(forearm) * 51, elbow[1] + math.cos(forearm) * 51)
        arms[name] = (shoulder, elbow, hand)
    return {'phase': phase, 'bob': bob, 'sway': sway, 'legs': legs, 'arms': arms}


class WalkRig:
    def __init__(self, directory, use_cycle=True):
        directory = Path(directory)
        self.layout = json.loads((directory / 'walk-rig-layout.json').read_text(encoding='utf-8'))
        self.cycle = None
        manifest = directory / 'walk-cycle.json'
        if use_cycle and manifest.exists():
            data = json.loads(manifest.read_text(encoding='utf-8'))
            if data.get('version') == CYCLE_VERSION:
                atlas = Image.open(directory / 'walk-cycle.png').convert('RGBA')
                w,h = data['cell']
                cols = data['columns']
                self.cycle = [atlas.crop(((i%cols)*w,(i//cols)*h,(i%cols+1)*w,(i//cols+1)*h)) for i in range(data['count'])]
        self.resize_cache = {}
        self.head_cache = {}
        sheet = Image.open(directory / 'walk-rig.png').convert('RGBA')
        self.parts = {name: sheet.crop(item['box']) for name, item in self.layout['parts'].items()}
        self.width_factors = {}
        for side in ('far', 'near'):
            for limb in ('arm', 'thigh', 'shin'):
                name = side + '_' + limb
                texture, factor = self.straighten(self.parts[name])
                self.parts[name] = texture
                self.width_factors[id(texture)] = factor
        # Preserve the approved compact head size and long tail length while
        # fitting the reusable artwork into the same character coordinates.
        head = self.parts['head']
        face = self.layout['head_face']
        cx, cy = (face[0] + face[2]) / 2, (face[1] + face[3]) / 2
        sx = 80. / (face[2] - face[0])
        sy = 192. / cy
        cut = min(head.height - 20, face[3] + 16)
        head_width = round(head.width * sx)
        upper_height = round(cut * sy)
        fitted = Image.new('RGBA', (head_width, 412))
        fitted.alpha_composite(head.crop((0, 0, head.width, cut)).resize((head_width, upper_height), Image.Resampling.LANCZOS))
        fitted.alpha_composite(head.crop((0, cut, head.width, head.height)).resize((head_width, 412 - upper_height), Image.Resampling.LANCZOS), (0, upper_height))
        self.head = Image.new('RGBA', (head_width + 20, 412))
        self.head.alpha_composite(fitted, (10, 0))
        self.head_tail_start = upper_height
        self.head_pivot = ((cx * sx + 10) / (head_width + 20), 192. / 412)
        self.leg_textures = {}
        for side in ('far', 'near'):
            # Join the inner lengths of both textures, excluding the outlined
            # round end caps. A continuous UV texture cannot expose knee rings.
            upper = self.parts[side + '_thigh']
            lower = self.parts[side + '_shin']
            def inner(image, physical_width):
                factor = self.width_factors[id(image)]
                return image.crop((0,round(image.height*.12),image.width,round(image.height*.88))).resize(
                    (round(physical_width*factor),144),Image.Resampling.LANCZOS)
            a,b=inner(upper,THIGH_WIDTH),inner(lower,SHIN_WIDTH)
            layer_a=Image.new('RGBA',(80,256));layer_b=Image.new('RGBA',(80,256))
            layer_a.alpha_composite(a,((80-a.width)//2,0))
            layer_b.alpha_composite(b,((80-b.width)//2,112))
            ramp=Image.new('L',(1,256))
            ramp.putdata([round(255*max(0.,min(1.,(y-114)/28))) for y in range(256)])
            self.leg_textures[side]=Image.composite(layer_b,layer_a,ramp.resize((80,256)))

    @staticmethod
    def straighten(image):
        """Register a curved limb texture by its local skin/sleeve centreline.
        Width is calibrated to the median cross section, not the full bbox."""
        alpha = image.getchannel('A')
        rows, widths = [], []
        for y in range(image.height):
            box = alpha.crop((0, y, image.width, y + 1)).point(lambda a:255 if a>100 else 0).getbbox()
            if box:
                rows.append((box[0] + box[2]) / 2)
                widths.append(box[2] - box[0])
            else:
                rows.append(rows[-1] if rows else image.width / 2)
                widths.append(0)
        # Smooth the sampling centreline to avoid following individual pixels.
        centers = [sum(rows[max(0,y-4):min(image.height,y+5)]) / len(rows[max(0,y-4):min(image.height,y+5)])
                   for y in range(image.height)]
        typical = median(v for v in widths[image.height//5:image.height*3//4] if v)
        width = max(widths) + 8
        mesh = []
        cuts = list(range(0, image.height, 4)) + [image.height]
        for y0, y1 in zip(cuts, cuts[1:]):
            a, b = centers[y0], centers[min(image.height-1,y1)]
            mesh.append(((0,y0,width,y1),(a-width/2,y0,b-width/2,y1,b+width/2,y1,a+width/2,y0)))
        return image.transform((width,image.height),Image.Transform.MESH,mesh,Image.Resampling.BICUBIC), width/typical

    def paste_pivot(self, canvas, image, pivot, position, angle, dimensions):
        # Place a joint at a fractional pixel, preserving antialiased motion.
        w, h = dimensions
        dimensions = (max(1, round(w)), max(1, round(h)))
        if image.size == dimensions:
            target = image
        else:
            key = (id(image), dimensions)
            if key not in self.resize_cache:
                self.resize_cache[key] = image.resize(dimensions, Image.Resampling.LANCZOS)
            target = self.resize_cache[key]
        px, py = pivot[0] * target.width, pivot[1] * target.height
        theta = math.radians(angle)
        c, s = math.cos(theta), math.sin(theta)
        corners = [(c * (x - px) + s * (y - py), -s * (x - px) + c * (y - py))
                   for x in (0, target.width) for y in (0, target.height)]
        x0 = math.floor(position[0] + min(x for x, y in corners)) - 1
        y0 = math.floor(position[1] + min(y for x, y in corners)) - 1
        x1 = math.ceil(position[0] + max(x for x, y in corners)) + 1
        y1 = math.ceil(position[1] + max(y for x, y in corners)) + 1
        # Inverse of the forward rotation around the selected joint.
        dx, dy = x0 - position[0], y0 - position[1]
        inverse = (c, -s, c * dx - s * dy + px,
                   s, c, s * dx + c * dy + py)
        rotated = target.transform((x1 - x0, y1 - y0), Image.Transform.AFFINE,
                                   inverse, Image.Resampling.BICUBIC)
        canvas.alpha_composite(rotated, (x0, y0))

    def segment(self, canvas, image, start, end, width, scale, overlap=3.):
        dx, dy = end[0] - start[0], end[1] - start[1]
        center = ((start[0] + end[0]) / 2 * scale, (start[1] + end[1]) / 2 * scale)
        angle = math.degrees(math.atan2(dx, dy))
        self.paste_pivot(canvas, image, (.5, .5), center, angle,
                         (width * self.width_factors.get(id(image),1.) * scale,
                          (math.hypot(dx, dy) + overlap * 2) * scale))

    def curved_layer(self, image, joints, scale, dimensions, half, source_joint=None):
        """Deform one continuous UV strip; no individual joint caps."""
        shoulder, elbow, hand = joints
        y0, y1 = shoulder[1], hand[1]
        left = math.floor((min(shoulder[0],elbow[0],hand[0])-half-10)*scale)
        top = math.floor((y0-3)*scale)
        right = math.ceil((max(shoulder[0],elbow[0],hand[0])+half+10)*scale)
        bottom = math.ceil((y1+3)*scale)
        width, height = right-left,bottom-top
        # A quadratic Bezier passes through the desired elbow at its y fraction.
        te = (elbow[1]-y0)/(y1-y0)
        control = (elbow[0]-(1-te)**2*shoulder[0]-te**2*hand[0])/(2*te*(1-te))
        def center(y):
            t=max(0.,min(1.,((top+y)/scale-y0)/(y1-y0)))
            return (1-t)**2*shoulder[0]+2*t*(1-t)*control+t*t*hand[0]
        def coords(x,y):
            physical_x=(left+x)/scale
            source_x=(physical_x-center(y))/(2*half)*image.width+image.width/2
            t=((top+y)/scale-y0)/(y1-y0)
            if source_joint is not None:
                t=(t/te*source_joint if t<te else source_joint+(t-te)/(1-te)*(1-source_joint))
            source_y=t*image.height
            return source_x,source_y
        mesh=[]
        cuts=list(range(0,height,3))+[height]
        for a,b in zip(cuts,cuts[1:]):
            quad=coords(0,a)+coords(0,b)+coords(width,b)+coords(width,a)
            mesh.append(((0,a,width,b),quad))
        texture=image.transform((width,height),Image.Transform.MESH,mesh,Image.Resampling.BICUBIC)
        layer=Image.new('RGBA',dimensions)
        layer.alpha_composite(texture,(left,top))
        return layer

    def arm_layer(self, side, joints, scale, dimensions):
        image=self.parts[side+'_arm']
        nominal=39. if side=='near' else 37.
        return self.curved_layer(image,joints,scale,dimensions,nominal*self.width_factors[id(image)]/2)

    @lru_cache(maxsize=256)
    def cycle_frame(self, index, size, mirror):
        image=self.cycle[index]
        dimensions=tuple(round(v*size/500) for v in CANVAS)
        if image.size!=dimensions:
            image=image.resize(dimensions,Image.Resampling.LANCZOS)
        return ImageOps.mirror(image) if mirror else image

    def render(self, phase, size, mirror=False):
        if self.cycle:
            return self.cycle_frame(round((phase%1)*len(self.cycle))%len(self.cycle),size,mirror)
        return self.render_procedural(phase,size,mirror)

    def render_procedural(self, phase, size, mirror=False):
        phase %= 1.
        pose = skeleton(phase)
        scale = size / 500
        out = Image.new('RGBA', tuple(round(v * scale) for v in CANVAS))
        for side in ('far', 'near'):
            leg = pose['legs'][side]
            out.alpha_composite(self.curved_layer(self.leg_textures[side],
                (leg['hip'],leg['knee'],leg['ankle']),scale,out.size,40.,.5))
            foot = leg['foot']
            self.paste_pivot(out, self.parts[side + '_shoe'], (16 / 52, 8 / 29),
                             (foot.x * scale, foot.y * scale), foot.angle, (52 * scale, 29 * scale))

        if size not in self.head_cache:
            self.head_cache[size] = self.head.resize(tuple(round(v * scale) for v in self.head.size), Image.Resampling.LANCZOS)
        head = self.head_cache[size]
        tail_start = self.head_tail_start * scale
        # Delayed motion grows towards tail tips; the face/scalp stay rigid.
        def tail_shift(y):
            depth = max(0., (y - tail_start) / (head.height - tail_start))
            return 5 * scale * depth ** 1.4 * math.sin(math.tau * phase - depth * .8)
        mesh = []
        cuts = [0, round(tail_start)] + [round(tail_start + (head.height - tail_start) * n / 6) for n in range(1, 7)]
        for y0, y1 in zip(cuts, cuts[1:]):
            a, b = tail_shift(y0), tail_shift(y1)
            mesh.append(((0, y0, head.width, y1),
                         (-a, y0, -b, y1, head.width - b, y1, head.width - a, y0)))
        head = head.transform(head.size, Image.Transform.MESH, mesh, Image.Resampling.BICUBIC)
        tilt = .45 * math.sin(math.tau * phase - .35)
        self.paste_pivot(out, head, self.head_pivot,
                         ((300 + pose['sway']) * scale, (230 + pose['bob']) * scale), tilt,
                         head.size)

        far_arm=self.arm_layer('far',pose['arms']['far'],scale,out.size)
        near_arm=self.arm_layer('near',pose['arms']['near'],scale,out.size)
        out.alpha_composite(far_arm)
        out.alpha_composite(near_arm)
        self.paste_pivot(out, self.parts['torso'], (.5, 0.),
                         ((282 + pose['sway']) * scale, (286 + pose['bob']) * scale),
                         .5 * math.sin(math.tau * phase), (132 * scale, 163 * scale))
        # Bury the shoulder cap under the cardigan, keeping the lower near arm
        # in front. A soft overlap avoids a floating round shoulder joint.
        alpha=near_arm.getchannel('A')
        ramp=Image.new('L',(1,out.height))
        shoulder_y=pose['arms']['near'][0][1]
        ramp.putdata([round(255*max(0.,min(1.,(y/scale-shoulder_y-16)/12))) for y in range(out.height)])
        alpha=ImageChops.multiply(alpha,ramp.resize(out.size))
        near_arm.putalpha(alpha)
        out.alpha_composite(near_arm)
        return ImageOps.mirror(out) if mirror else out
