"""莲儿桌宠：Windows 10/11，Python 3.10+ 与 Pillow。

逐像素透明的原生 Windows 桌宠。拖动移动，单击说话，右键打开菜单。
同人图像经过切分、关节绑定与连续动作处理；声音支持本地导入。
"""

from __future__ import annotations

import argparse
import ctypes as C
from ctypes import wintypes as W
from datetime import datetime
from functools import lru_cache
import json
import logging
import math
import os
from pathlib import Path
import random
import sys
import time
import wave
import winsound

from PIL import Image, ImageChops, ImageDraw, ImageFont
from motion import Motion, breathing
from sprites import Sprites, PoseMixer
from music import MusicLibrary
from activities import Activities, greeting
from action_rig import LABELS, POUNCE_DURATION
from tray import TrayIcon,TRAY_MESSAGE,RESTORE_MESSAGE
from voice import VoiceLibrary,VoicePlayer


BASE = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
RESOURCES = Path(getattr(sys, "_MEIPASS", BASE))
TITLE = "莲儿桌宠 · 宫内莲华 · 新版"
SIZES = (160, 200, 250)
PHRASES = (
    "喵帕斯～你，咱在这里。",
    "咦，鼠标跑到这边来了。",
    "忙完这一小段，就伸个懒腰吧。",
    "今天也发现一点新东西了吗？",
    "咱想画一只很大的狸猫。",
    "你慢慢来，咱陪着你。",
    "这里的风，好像也慢悠悠的。",
    "咱把今天的小发现，放进心里啦。",
    "咦，刚刚是不是有一只看不见的狸猫？",
    "你，要一起玩一局猜拳吗？",
    "笛子已经准备好啦，右键可以点歌。",
    "这个小角落，好像很适合画画。",
)

user32 = C.WinDLL("user32", use_last_error=True)
gdi32 = C.WinDLL("gdi32", use_last_error=True)
kernel32 = C.WinDLL("kernel32", use_last_error=True)
LRESULT = C.c_ssize_t
WNDPROC = C.WINFUNCTYPE(LRESULT, W.HWND, W.UINT, W.WPARAM, W.LPARAM)


class WNDCLASS(C.Structure):
    _fields_ = [("style", W.UINT), ("proc", WNDPROC), ("class_extra", C.c_int),
                ("window_extra", C.c_int), ("instance", W.HINSTANCE), ("icon", W.HANDLE),
                ("cursor", W.HANDLE), ("background", W.HBRUSH),
                ("menu_name", W.LPCWSTR), ("class_name", W.LPCWSTR)]


class BITMAPINFOHEADER(C.Structure):
    _fields_ = [("size", W.DWORD), ("width", W.LONG), ("height", W.LONG),
                ("planes", W.WORD), ("bit_count", W.WORD), ("compression", W.DWORD),
                ("size_image", W.DWORD), ("x_pels", W.LONG), ("y_pels", W.LONG),
                ("colors_used", W.DWORD), ("colors_important", W.DWORD)]


class BITMAPINFO(C.Structure):
    _fields_ = [("header", BITMAPINFOHEADER), ("colors", W.DWORD * 1)]


class BLEND(C.Structure):
    _pack_ = 1
    _fields_ = [("operation", W.BYTE), ("flags", W.BYTE),
                ("constant_alpha", W.BYTE), ("alpha_format", W.BYTE)]


class MONITORINFO(C.Structure):
    _fields_ = [("size", W.DWORD), ("monitor", W.RECT), ("work", W.RECT), ("flags", W.DWORD)]


def signature(lib, name, result, *args):
    fn = getattr(lib, name)
    fn.restype, fn.argtypes = result, args
    return fn


# Explicit pointer-sized signatures are essential on 64-bit Windows.
signature(kernel32, "GetModuleHandleW", W.HMODULE, W.LPCWSTR)
signature(kernel32, "CreateMutexW", W.HANDLE, C.c_void_p, W.BOOL, W.LPCWSTR)
signature(kernel32, "CloseHandle", W.BOOL, W.HANDLE)
signature(user32, "RegisterClassW", W.ATOM, C.POINTER(WNDCLASS))
signature(user32, "CreateWindowExW", W.HWND, W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD,
          C.c_int, C.c_int, C.c_int, C.c_int, W.HWND, W.HMENU, W.HINSTANCE, C.c_void_p)
signature(user32, "DefWindowProcW", LRESULT, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
signature(user32, "GetDC", W.HDC, W.HWND)
signature(user32, "ReleaseDC", C.c_int, W.HWND, W.HDC)
signature(user32, "UpdateLayeredWindow", W.BOOL, W.HWND, W.HDC, C.POINTER(W.POINT),
          C.POINTER(W.SIZE), W.HDC, C.POINTER(W.POINT), W.DWORD, C.POINTER(BLEND), W.DWORD)
signature(user32, "SetWindowPos", W.BOOL, W.HWND, W.HWND, C.c_int, C.c_int, C.c_int, C.c_int, W.UINT)
signature(user32, "SetTimer", C.c_size_t, W.HWND, C.c_size_t, W.UINT, C.c_void_p)
signature(user32, "KillTimer", W.BOOL, W.HWND, C.c_size_t)
signature(user32, "LoadCursorW", W.HANDLE, W.HINSTANCE, C.c_void_p)
signature(user32, "LoadImageW", W.HANDLE, W.HINSTANCE, W.LPCWSTR, W.UINT, C.c_int, C.c_int, W.UINT)
signature(user32, "ShowWindow", W.BOOL, W.HWND, C.c_int)
signature(user32, "FindWindowW", W.HWND, W.LPCWSTR, W.LPCWSTR)
signature(user32, "PostMessageW", W.BOOL, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
signature(user32, "RegisterWindowMessageW", W.UINT, W.LPCWSTR)
signature(user32, "GetKeyState", W.SHORT, C.c_int)
signature(user32, "SetCapture", W.HWND, W.HWND)
signature(user32, "ReleaseCapture", W.BOOL)
signature(user32, "GetCursorPos", W.BOOL, C.POINTER(W.POINT))
signature(user32, "GetWindowRect", W.BOOL, W.HWND, C.POINTER(W.RECT))
signature(user32, "GetMessageW", C.c_int, C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT)
signature(user32, "TranslateMessage", W.BOOL, C.POINTER(W.MSG))
signature(user32, "DispatchMessageW", LRESULT, C.POINTER(W.MSG))
signature(user32, "DestroyWindow", W.BOOL, W.HWND)
signature(user32, "PostQuitMessage", None, C.c_int)
signature(user32, "CreatePopupMenu", W.HMENU)
signature(user32, "AppendMenuW", W.BOOL, W.HMENU, W.UINT, C.c_size_t, W.LPCWSTR)
signature(user32, "TrackPopupMenu", W.UINT, W.HMENU, W.UINT, C.c_int, C.c_int, C.c_int, W.HWND, C.c_void_p)
signature(user32, "DestroyMenu", W.BOOL, W.HMENU)
signature(user32, "SetForegroundWindow", W.BOOL, W.HWND)
signature(user32, "MonitorFromPoint", W.HANDLE, W.POINT, W.DWORD)
signature(user32, "GetMonitorInfoW", W.BOOL, W.HANDLE, C.POINTER(MONITORINFO))
signature(user32, "MessageBoxW", C.c_int, W.HWND, W.LPCWSTR, W.LPCWSTR, W.UINT)
signature(gdi32, "CreateCompatibleDC", W.HDC, W.HDC)
signature(gdi32, "CreateDIBSection", W.HBITMAP, W.HDC, C.POINTER(BITMAPINFO), W.UINT,
          C.POINTER(C.c_void_p), W.HANDLE, W.DWORD)
signature(gdi32, "SelectObject", W.HANDLE, W.HDC, W.HANDLE)
signature(gdi32, "DeleteObject", W.BOOL, W.HANDLE)
signature(gdi32, "DeleteDC", W.BOOL, W.HDC)


def work_area(x=0, y=0):
    monitor = user32.MonitorFromPoint(W.POINT(int(x), int(y)), 2)
    info = MONITORINFO()
    info.size = C.sizeof(info)
    if not user32.GetMonitorInfoW(monitor, C.byref(info)):
        raise C.WinError(C.get_last_error())
    return info.work


def cursor():
    point = W.POINT()
    user32.GetCursorPos(C.byref(point))
    return point.x, point.y


class LayeredSurface:
    def __init__(self, width, height):
        self.width, self.height = width, height
        self.screen = user32.GetDC(None)
        self.dc = gdi32.CreateCompatibleDC(self.screen)
        self.bits = C.c_void_p()
        info = BITMAPINFO()
        info.header = BITMAPINFOHEADER(C.sizeof(BITMAPINFOHEADER), width, -height, 1, 32, 0, width * height * 4, 0, 0, 0, 0)
        self.bitmap = gdi32.CreateDIBSection(self.screen, C.byref(info), 0, C.byref(self.bits), None, 0)
        if not self.bitmap:
            raise C.WinError(C.get_last_error())
        self.original = gdi32.SelectObject(self.dc, self.bitmap)

    def show(self, hwnd, image, x, y):
        r, g, b, a = image.split()
        # UpdateLayeredWindow expects premultiplied BGRA, not straight PNG alpha.
        premultiplied = Image.merge("RGBA", (ImageChops.multiply(r, a), ImageChops.multiply(g, a), ImageChops.multiply(b, a), a))
        data = premultiplied.tobytes("raw", "BGRA")
        C.memmove(self.bits, data, len(data))
        position, source = W.POINT(round(x), round(y)), W.POINT(0, 0)
        size, blend = W.SIZE(self.width, self.height), BLEND(0, 0, 255, 1)
        if not user32.UpdateLayeredWindow(hwnd, self.screen, C.byref(position), C.byref(size), self.dc,
                                         C.byref(source), 0, C.byref(blend), 2):
            raise C.WinError(C.get_last_error())

    def close(self):
        gdi32.SelectObject(self.dc, self.original)
        gdi32.DeleteObject(self.bitmap)
        gdi32.DeleteDC(self.dc)
        user32.ReleaseDC(None, self.screen)


class Pet:
    def __init__(self, args):
        self.args = args
        self.rng = random.Random()
        self.settings_file = Path(getattr(args,'settings_file',None) or BASE / "data" / "settings.json")
        saved = {}
        try:
            saved = json.loads(self.settings_file.read_text(encoding="utf-8-sig"))
            if not isinstance(saved, dict):
                saved = {}
        except (OSError, ValueError):
            pass
        self.size = saved.get("size", 200)
        if self.size not in SIZES:
            self.size = 200
        self.topmost = bool(saved.get("topmost", True))
        self.quiet = bool(saved.get("quiet", False))
        self.sound = bool(saved.get("sound", True))
        self.volume = saved.get('volume',50)
        if self.volume not in (25,50,75,100):self.volume=50
        self.voice_enabled=bool(saved.get('voice_enabled',True))
        self.voice_volume=saved.get('voice_volume',50)
        if self.voice_volume not in (25,50,75,100):self.voice_volume=50
        self.voices=VoiceLibrary(RESOURCES,BASE)
        self.voice_player=VoicePlayer()
        self.motion = Motion(size=self.size, direction=self.rng.choice((-1, 1)))
        self.music = MusicLibrary(RESOURCES,BASE)
        self.selected_track = self.music.get(getattr(args,'track',None) or saved.get('track','hidamari')).id
        self.music_mode = saved.get('music_mode','once')
        if self.music_mode not in ('once','repeat','shuffle'):self.music_mode='once'
        self.music_session = False
        self.active_track = self.music.get(self.selected_track)
        self.activities = Activities(affection=max(0,min(100,int(saved.get('affection',0)))),
                                     touches=max(0,int(saved.get('touches',0))))
        self.particles = []
        self.in_menu = False
        self.audio_playing = False
        self.audio_starts = 0
        self.audio_file = self.music.playback_path(self.active_track,self.volume)
        self.motion.flute_seconds = self.active_track.duration
        self.drag_anchor = None
        self.dragged = False
        self.head_touch = None
        self.touch_heart_at = 0.
        self.next_expression = time.monotonic()+self.rng.uniform(14,26)
        self.pounce_stage = 0
        self.pounce_voice_pending = False
        self.speech = ""
        self.speech_until = self.wave_until = self.blink_until = 0.0
        self.started = self.last_tick = time.monotonic()
        self.next_blink = self.started + 2.7
        self.next_talk = self.started + self.rng.uniform(65, 110)
        self.frames = 0
        self.last_diagnostic = 0
        self.hwnd = None
        self.surface = None
        self.tray = None
        self.hidden = False
        self.hidden_at = 0.
        self.taskbar_message = 0
        self.load_sprites()
        fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        font_path = fonts / "msyh.ttc"
        if not font_path.exists():
            font_path = fonts / "simhei.ttf"
        self.font = ImageFont.truetype(str(font_path), 17)
        self.small_font = ImageFont.truetype(str(font_path), 13)
        self.dimensions()
        bounds = work_area()
        self.x = saved.get("x", bounds.right - self.width - 70)
        self.y = saved.get("y", bounds.bottom - self.height - 18)
        if not isinstance(self.x, (float, int)) or not math.isfinite(self.x):
            self.x = bounds.right - self.width - 70
        if not isinstance(self.y, (float, int)) or not math.isfinite(self.y):
            self.y = bounds.bottom - self.height - 18
        self.clamp()

        # Count animation time from after asset registration. Otherwise startup
        # preprocessing looks like a long lost frame and shortens timed states.
        self.started = self.last_tick = time.monotonic()
        self.next_blink = self.started + 2.7
        self.next_talk = self.started + self.rng.uniform(65, 110)
        self.activities.reminder(saved.get('rest_minutes',0),self.started)

    @property
    def sleeping(self):
        return self.motion.state in ('sleep', 'sleep_in')

    @property
    def walking(self):
        return self.motion.state in ('walk', 'turn')

    def load_sprites(self):
        self.sprites = Sprites(RESOURCES / 'assets')
        self.pose_mixer = PoseMixer()

    def dimensions(self):
        self.width, self.height = max(320, self.size + 70), self.size + 136
        self.sprites.pose.cache_clear()
        self.sprites.premultiplied.cache_clear()
        self.pose_mixer.reset()
        self.sprites.actions.cached_frame.cache_clear()
        self.motion.size = self.size
        if self.surface:
            self.surface.close()
            self.surface = LayeredSurface(self.width, self.height)

    def clamp(self):
        area = work_area(self.x + self.width / 2, self.y + self.height / 2)
        self.x = min(max(self.x, area.left), max(area.left, area.right - self.width))
        self.y = min(max(self.y, area.top), max(area.top, area.bottom - self.height))

    @lru_cache(maxsize=8)
    def bubble_image(self, text, width, canvas_height):
        frame=Image.new('RGBA',(width,canvas_height))
        draw = ImageDraw.Draw(frame)
        max_width = width - 54
        lines, line = [], ""
        for char in text:
            if char=='\n':
                lines.append(line);line='';continue
            if draw.textlength(line + char, font=self.font) > max_width:
                lines.append(line)
                line = char
            else:
                line += char
        if line:
            lines.append(line)
        height = min(94, len(lines) * 25 + 24)
        left, right, top = 13, width - 13, 9
        draw.rounded_rectangle((left + 2, top + 4, right + 2, top + height + 4), radius=18, fill=(42, 27, 57, 32))
        draw.rounded_rectangle((left, top, right, top + height), radius=18,
                               fill=(255, 252, 246, 249), outline=(192, 166, 214, 255), width=2)
        middle = width // 2
        draw.polygon(((middle - 9, top + height - 2), (middle + 9, top + height - 2),
                      (middle, top + height + 10)), fill=(255, 252, 246, 249))
        for i, text in enumerate(lines[:3]):
            draw.text((left + 14, top + 10 + i * 25), text, font=self.font, fill=(84, 65, 100, 255))
        return frame

    def bubble(self, frame):
        if self.speech:frame.alpha_composite(self.bubble_image(self.speech,self.width,self.height))

    def game_buttons(self):
        width=(self.width-48)/3
        return [(round(24+i*width),52,round(24+(i+1)*width-8),88) for i in range(3)]

    def overlays(self,frame,now):
        draw=ImageDraw.Draw(frame)
        if self.activities.game_open:
            draw.rounded_rectangle((13,9,self.width-13,101),radius=16,fill=(255,252,246,250),outline='#bca5cf',width=2)
            draw.text((25,21),'猜拳，咱已经出好啦。',font=self.font,fill='#594966')
            for box,label in zip(self.game_buttons(),('石头','剪刀','布')):
                draw.rounded_rectangle(box,radius=9,fill='#f1e7f7',outline='#b59fc8')
                draw.text((box[0]+12,box[1]+9),label,font=self.font,fill='#594966')
        elif self.motion.state.startswith('flute'):
            title='曲目：'+self.active_track.title
            while draw.textlength(title,font=self.small_font)>self.width-56:title=title[:-2]+'…'
            draw.rounded_rectangle((18,20,self.width-18,81),radius=14,fill=(255,252,246,241),outline='#c9b5d7')
            draw.text((28,31),title,font=self.small_font,fill='#665174')
            progress=min(1.,self.motion.age/self.motion.flute_seconds) if self.motion.state=='flute_play' else (1. if self.motion.state=='flute_out' else 0.)
            draw.rounded_rectangle((29,61,self.width-29,65),radius=2,fill='#e5dbea')
            draw.rounded_rectangle((29,61,29+(self.width-58)*progress,65),radius=2,fill='#b49bc9')
        if self.motion.state=='pounce' and 1.55<self.motion.age<2.5:
            # Dust spreads behind the slide, then settles; no screen shake.
            progress=(self.motion.age-1.55)/.95
            direction=self.motion.direction
            for i in range(5):
                x=self.width/2-direction*(self.size*.3+i*6+progress*24)
                y=self.height-18-i%2*5-progress*9
                radius=2+progress*3
                draw.ellipse((x-radius,y-radius,x+radius,y+radius),fill=(190,173,150,round(85*(1-progress))))
        self.particles=[p for p in self.particles if now-p['born']<1.7]
        for p in self.particles:
            age=now-p['born'];alpha=round(230*(1-age/1.7))
            x=p['x']+p['vx']*age;y=p['y']-p['rise']*age;color=(*p['color'],alpha)
            if p['text']=='♥':
                draw.ellipse((x,y,x+8,y+8),fill=color)
                draw.ellipse((x+6,y,x+14,y+8),fill=color)
                draw.polygon(((x,y+4),(x+14,y+4),(x+7,y+14)),fill=color)
            else:
                points=[]
                for k in range(10):
                    angle=-math.pi/2+k*math.pi/5;radius=7 if k%2==0 else 3
                    points.append((x+7+math.cos(angle)*radius,y+7+math.sin(angle)*radius))
                draw.polygon(points,fill=color)

    def render(self, now):
        pose = self.motion.sample()
        if self.motion.state=='flute_play':
            pose=self.active_track.finger_pose(self.motion.age) or pose
        if self.motion.state == 'idle' and now < self.blink_until:
            elapsed = .24 - (self.blink_until - now)
            closure = min(1., elapsed / .075) if elapsed < .125 else max(0., 1 - (elapsed - .125) / .115)
            pose = ('blink', 0, 0, closure, False)
        sprite = self.pose_mixer.render(self.sprites, pose, (self.motion.state, pose[-1]), now, self.size)
        frame = Image.new("RGBA", (self.width, self.height))
        draw = ImageDraw.Draw(frame)
        ground = self.height - 13
        center = self.width // 2
        draw.ellipse((center - 43, ground - 5, center + 43, ground + 4), fill=(46, 32, 63, 36))
        # The rig moves hips/head while the stance foot stays at ground level.
        # A whole-sprite bounce here would make a planted foot leave the floor.
        bounce = 0 if self.walking else breathing(now - self.started, self.size, self.sleeping)
        # Keep fractional movement inside the layer, instead of rounding each
        # tiny breath and step into a visible one-pixel jump.
        px = (self.width - sprite.width) / 2 + self.x - round(self.x)
        py = ground - self.sprites.foot(self.size) - bounce + self.y - round(self.y)
        ix, iy = math.floor(px), math.floor(py)
        if px != ix or py != iy:
            sprite = sprite.transform(sprite.size, Image.Transform.AFFINE,
                                      (1, 0, -(px - ix), 0, 1, -(py - iy)),
                                      Image.Resampling.BICUBIC)
        frame.alpha_composite(sprite, (ix, iy))
        if self.sleeping:
            draw.text((center + self.size * .29, 118), "z Z", font=self.font, fill=(151, 129, 185, 210))
        self.bubble(frame)
        self.overlays(frame,now)
        return frame, self.motion.state

    def voice_line(self,cue):
        if not cue or not self.voice_enabled or self.hidden or self.hwnd is None:return False
        if self.motion.state.startswith('flute') or self.audio_playing:return False
        clip=self.voices.choose(cue,self.rng)
        if clip is None:return False
        if not self.voice_player.play(clip,self.voice_volume):return False
        self.speech=clip.subtitle
        self.speech_until=time.monotonic()+max(3.5,clip.duration+.8)
        return True

    def toggle_voice(self):
        self.voice_enabled=not self.voice_enabled
        if not self.voice_enabled:self.voice_player.stop()
        self.speech='日语原声打开啦。' if self.voice_enabled else '咱先安静地陪着你。'
        self.speech_until=time.monotonic()+3
        self.save()

    def say(self, text=None, greeting=False,voice_cue=None):
        now = time.monotonic()
        if greeting and self.motion.state.startswith('flute'):self.interrupt_music()
        if self.sleeping:
            self.motion.wake()
        self.speech = text or self.rng.choice(PHRASES)
        self.speech_until = now + 6
        self.wave_until = now + (2.8 if greeting else 1.3)
        if greeting or self.motion.state == 'idle':
            self.motion.greet()
        self.next_talk = now + self.rng.uniform(65, 110)
        self.voice_line('greet' if greeting else (voice_cue or ('talk' if text is None else None)))

    def save(self):
        try:
            self.settings_file.parent.mkdir(exist_ok=True)
            data = {"x": round(self.x), "y": round(self.y), "size": self.size,
                    "topmost": self.topmost, "quiet": self.quiet, "sound": self.sound,
                    'volume':self.volume,'track':self.selected_track,'music_mode':self.music_mode,
                    'voice_enabled':self.voice_enabled,'voice_volume':self.voice_volume,
                    'affection':self.activities.affection,'touches':self.activities.touches,
                    'rest_minutes':self.activities.rest_minutes}
            temp = self.settings_file.with_suffix(".tmp")
            temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(self.settings_file)
        except OSError:
            logging.exception("Could not save settings")

    def toggle_sleep(self):
        self.interrupt_music()
        self.activities.game_open=False
        self.motion.wake() if self.sleeping else self.motion.sleep()
        if not self.sleeping:self.activities.reminder(self.activities.rest_minutes,time.monotonic())
        self.speech = "咱睡一小会儿……" if self.sleeping else "睡醒啦。喵帕斯～"
        self.speech_until = time.monotonic() + 4
        self.voice_line('sleep' if self.sleeping else 'wake')

    def interrupt_music(self):
        self.end_head_touch()
        self.pounce_voice_pending=False
        self.voice_player.stop()
        self.music_session=False
        winsound.PlaySound(None,0)
        self.audio_playing=False

    def play_flute(self, track_id=None, force=False):
        if self.motion.state.startswith('flute') and track_id is None and not force:
            self.music_session=False
            self.motion.stop()
            self.audio_events()
            return
        self.interrupt_music()
        self.motion.enter('idle')
        if track_id is not None:self.selected_track=self.music.get(track_id).id
        self.active_track=self.music.get(self.selected_track)
        self.audio_file=self.music.playback_path(self.active_track,self.volume)
        self.motion.flute_seconds=self.active_track.duration
        self.activities.game_open=False
        self.music_session=True
        self.motion.flute()
        self.speech = ''
        self.next_talk = time.monotonic() + self.rng.uniform(65, 110)

    def next_song(self):
        choices=[t for t in self.music.tracks if t.id!=self.selected_track]
        self.play_flute(self.rng.choice(choices or self.music.tracks).id,True)

    def emote(self,text='♥',color=(225,125,164),count=6):
        now=time.monotonic()
        cy=self.height-13-self.size*(.30 if text=='✦' else .90)
        for i in range(count):
            self.particles.append({'born':now,'x':self.width/2+self.rng.uniform(-32,25),
                'y':cy+self.rng.uniform(-20,8),'vx':self.rng.uniform(-13,13),
                'rise':self.rng.uniform(22,40),'text':text,'color':color})

    def pet_head(self, held=False):
        self.interrupt_music();self.activities.game_open=False
        self.activities.pet();self.motion.pet(held);self.emote(count=3)
        self.touch_heart_at=time.monotonic()+1.
        self.say(self.rng.choice(('嗯……暖暖的。','咱的呆毛，翘起来了。','是你的手。咱知道的。','再摸一小会儿，也可以。')),voice_cue='pet')
        self.save()

    def end_head_touch(self):
        if getattr(self,'head_touch',None) is not None:
            self.head_touch=None
            self.motion.release_pet()
            user32.ReleaseCapture()

    def head_hit(self,x,y):
        if self.activities.game_open or self.motion.state in ('pounce','drag') or self.sleeping:return False
        face_y=self.height-13-self.size*.62
        return abs(x-self.width/2)<self.size*.27 and face_y-self.size*.36<y<face_y+self.size*.18

    def show_expression(self,index=None):
        self.interrupt_music();self.activities.game_open=False
        if index is None:index=self.rng.choice((0,1,2,3,4,5,6))
        self.motion.emote(index)
        phrases=('咱在想，云会不会也迷路。','咦，这个是什么？','今天有一点点高兴的说。',
                 '嗯……风轻轻的。','咱有在认真听哦。','这次，咱要认真起来。','咦，刚刚动了一下？','膝盖呀……咱先歇一会儿。')
        self.speech=phrases[index];self.speech_until=time.monotonic()+3.6
        self.voice_line('curious' if index in (0,1,6) else ('happy' if index in (2,3) else 'talk'))
        self.next_expression=time.monotonic()+self.rng.uniform(20,38)

    def start_pounce(self):
        if self.motion.state=='pounce':return
        self.interrupt_music();self.activities.game_open=False
        area=work_area(self.x+self.width/2,self.y+self.height/2)
        room_right=area.right-self.width-self.x;room_left=self.x-area.left
        direction=1 if room_right>=room_left else -1
        self.motion.pounce(direction);self.pounce_stage=0
        self.speech='ダイナマイ！';self.speech_until=time.monotonic()+1.7
        self.pounce_voice_pending=True
        self.next_expression=time.monotonic()+self.rng.uniform(20,38)

    def pounce_events(self,now):
        if self.motion.state!='pounce':
            self.pounce_voice_pending=False
            return
        # Request the short cry during anticipation, just before lift at .48s.
        # Device opening stays on the audio worker, outside the drawing loop.
        if self.pounce_voice_pending and self.motion.age>=.30:
            self.pounce_voice_pending=False
            self.voice_line('pounce')
        if self.motion.age>=2.6 and self.pounce_stage==0:
            self.pounce_stage=1;self.speech='膝盖……蹭到了的说。咱歇一小会儿。';self.speech_until=now+3.
            self.voice_line('rest')

    def feed(self):
        self.interrupt_music();self.activities.game_open=False
        self.activities.feed();self.motion.pet();self.emote('✦',(235,170,78),8)
        self.say(self.rng.choice(('咔嚓。甜甜的，谢谢你。','这颗糖，咱慢慢吃。','好吃的说。给你留一颗。')),voice_cue='feed')
        self.save()

    def toggle_follow(self):
        self.interrupt_music();self.activities.game_open=False
        self.activities.follow=not self.activities.follow
        self.motion.enter('idle')
        self.say('咱跟着鼠标走，等等咱。' if self.activities.follow else '咱在这里等你。',voice_cue='follow' if self.activities.follow else 'stop')

    def open_game(self):
        self.interrupt_music();self.motion.enter('idle');self.speech=''
        self.particles.clear()
        if self.activities.game_open:self.activities.game_open=False
        else:self.activities.start_game(self.rng)

    def choose_hand(self,choice):
        result=self.activities.choose(choice)
        if result is None:return
        opponent,outcome=result
        text={'draw':'一样的！再来一局吧。','win':'你赢啦，咱下次会想个办法。','lose':'咱赢啦。是你偷偷让着咱吗？'}[outcome]
        self.motion.greet();self.say('咱出'+('石头','剪刀','布')[opponent]+'。'+text)
        self.emote('★' if outcome!='lose' else '♪',(205,151,204),5)

    def on_click(self,x,y):
        if self.activities.game_open:
            for index,(a,b,c,d) in enumerate(self.game_buttons()):
                if a<=x<=c and b<=y<=d:self.choose_hand(index);return
            return
        if self.motion.state=='pounce':return
        if self.head_hit(x,y):
            self.pet_head()
        elif y>self.height-13-self.size*.20:
            self.interrupt_music();self.motion.walk()
            self.say('咦，是叫咱出发吗？咱去看看。')
        else:
            self.show_expression()

    def audio_events(self):
        for event in self.motion.drain_events():
            if event == 'audio_start' and self.sound:
                self.voice_player.stop()
                winsound.PlaySound(str(self.audio_file), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
                self.audio_playing = True
                self.audio_starts += 1
            elif event == 'audio_stop':
                winsound.PlaySound(None, 0)
                self.audio_playing = False

    def menu(self):
        menu = user32.CreatePopupMenu()
        self.in_menu=True
        def add(command, label, checked=False):
            user32.AppendMenuW(menu, 8 if checked else 0, command, label)
        def item(target,command,label,checked=False):
            user32.AppendMenuW(target,8 if checked else 0,command,label)
        add(1, "喵帕斯～")
        add(2, "说句话")
        add(3, "停下来" if self.walking else "散散步", self.walking)
        add(4, "醒来啦" if self.sleeping else "睡一会儿", self.sleeping)
        add(5, "收起笛子" if self.motion.state.startswith('flute') else "吹一小段笛子 ♪", self.motion.state.startswith('flute'))
        songs=user32.CreatePopupMenu()
        for i,track in enumerate(self.music.tracks):
            item(songs,1000+i,track.title,self.selected_track==track.id)
        user32.AppendMenuW(songs,0x800,0,None)
        item(songs,30,'随机换一首')
        item(songs,31,'重新扫描自定义曲目')
        item(songs,32,'打开自定义曲目文件夹')
        user32.AppendMenuW(menu,0x10,songs,'选一首曲子 ♪')
        modes=user32.CreatePopupMenu()
        for command,key,label in ((300,'once','吹完这一首'),(301,'repeat','单曲循环'),(302,'shuffle','随机连播')):
            item(modes,command,label,self.music_mode==key)
        user32.AppendMenuW(menu,0x10,modes,'演奏方式')
        volumes=user32.CreatePopupMenu()
        for i,value in enumerate((25,50,75,100)):
            item(volumes,400+i,f'{value}%',self.volume==value)
        user32.AppendMenuW(menu,0x10,volumes,'吹笛音量')
        voices=user32.CreatePopupMenu()
        item(voices,50,'日语原声',self.voice_enabled)
        item(voices,51,'试听：にゃんぱす～')
        for i,value in enumerate((25,50,75,100)):item(voices,450+i,f'语音音量 {value}%',self.voice_volume==value)
        user32.AppendMenuW(voices,0x800,0,None)
        item(voices,52,'重新读取原声包')
        item(voices,53,'打开原声包文件夹')
        user32.AppendMenuW(menu,0x10,voices,'说话语音')
        games=user32.CreatePopupMenu()
        item(games,40,'摸摸头 ♥')
        item(games,41,'喂一颗糖')
        item(games,42,'不跟了' if self.activities.follow else '跟随鼠标',self.activities.follow)
        item(games,43,'一起猜拳')
        item(games,45,'ダイナマイ！飞扑 · F7')
        expressions=user32.CreatePopupMenu()
        for i,label in enumerate(LABELS):item(expressions,600+i,label)
        user32.AppendMenuW(games,0x10,expressions,'莲华的小表情 · F8')
        user32.AppendMenuW(games,0x800,0,None)
        user32.AppendMenuW(games,1,44,f'亲近度 {self.activities.affection}/100 · 互动 {self.activities.touches} 次')
        user32.AppendMenuW(menu,0x10,games,'一起玩')
        reminders=user32.CreatePopupMenu()
        for i,value in enumerate((0,25,50)):
            item(reminders,500+i,'关闭' if not value else f'{value} 分钟提醒一次',self.activities.rest_minutes==value)
        user32.AppendMenuW(menu,0x10,reminders,'休息提醒')
        user32.AppendMenuW(menu, 0x800, 0, None)
        for command, size, label in ((10, 160, "小小只"), (11, 200, "刚刚好"), (12, 250, "大一点")):
            add(command, label, self.size == size)
        user32.AppendMenuW(menu, 0x800, 0, None)
        add(20, "始终置顶", self.topmost)
        add(21, "安静陪伴（关闭主动台词）", self.quiet)
        add(22, "吹笛声音", self.sound)
        add(90, "收纳进系统托盘 · Esc")
        add(99, "完全退出 · Ctrl+Q")
        x, y = cursor()
        user32.SetForegroundWindow(self.hwnd)
        command = user32.TrackPopupMenu(menu, 0x100 | 0x2, x, y, 0, self.hwnd, None)
        user32.DestroyMenu(menu)
        self.in_menu=False
        if command == 1:
            self.say("喵帕斯～你，咱来陪你啦。", True)
        elif command == 2:
            self.say()
        elif command == 3:
            self.interrupt_music();self.activities.game_open=False
            self.motion.stop() if self.walking else self.motion.walk()
            self.say("咱去这边看看。" if self.walking else "咱就在这里陪着你。")
        elif command == 4:
            self.toggle_sleep()
        elif command == 5:
            self.play_flute()
        elif 1000<=command<1000+len(self.music.tracks):
            self.play_flute(self.music.tracks[command-1000].id,True)
        elif command==30:
            self.next_song()
        elif command==31:
            self.interrupt_music();self.motion.enter('idle')
            self.music.reload()
            self.selected_track=self.music.get(self.selected_track).id
            self.say(f'曲目重新找好啦，一共有 {len(self.music.tracks)} 首。')
        elif command==32:
            os.startfile(str(BASE/'music'))
        elif command in (300,301,302):
            self.music_mode=('once','repeat','shuffle')[command-300]
        elif command in (400,401,402,403):
            self.volume=(25,50,75,100)[command-400]
            if self.motion.state.startswith('flute'):
                self.play_flute(self.selected_track,True)
        elif command==50:
            self.toggle_voice()
        elif command==51:
            self.interrupt_music();self.motion.enter('idle')
            self.say('にゃんぱす～',True)
        elif 450<=command<=453:
            self.voice_volume=(25,50,75,100)[command-450]
        elif command==52:
            self.voice_player.stop();self.voices.reload()
            self.speech=f'原声包读取好啦，共 {len(self.voices.clips)} 条。';self.speech_until=time.monotonic()+4
        elif command==53:os.startfile(str(self.voices.custom))
        elif command==40:self.pet_head()
        elif command==41:self.feed()
        elif command==42:self.toggle_follow()
        elif command==43:self.open_game()
        elif command==45:self.start_pounce()
        elif 600<=command<=607:self.show_expression(command-600)
        elif command in (500,501,502):
            self.activities.reminder((0,25,50)[command-500],time.monotonic())
            self.say('咱把休息提醒收好啦。' if not self.activities.rest_minutes else '到时候，咱会轻轻叫你休息一下。')
        elif command in (10, 11, 12):
            old_bottom = self.y + self.height
            self.size = SIZES[command - 10]
            self.dimensions()
            self.y = old_bottom - self.height
            self.clamp()
        elif command == 20:
            self.topmost = not self.topmost
            self.zorder()
        elif command == 21:
            self.quiet = not self.quiet
            self.speech = ""
        elif command == 22:
            self.sound = not self.sound
            if not self.sound:
                winsound.PlaySound(None, 0)
                self.audio_playing = False
        elif command == 90:
            self.hide_to_tray()
            return
        elif command == 99:
            self.exit_app()
            return
        self.last_tick = time.monotonic()
        self.save()

    def zorder(self):
        # Only this application's own window is affected.
        user32.SetWindowPos(self.hwnd, W.HWND(-1 if self.topmost else -2), 0, 0, 0, 0, 0x13)

    def hide_to_tray(self):
        if self.hidden:return True
        if self.tray is None or (not self.tray.active and not self.tray.add()):
            user32.MessageBoxW(self.hwnd,'托盘图标暂时没能创建，咱先留在桌面上。',TITLE,0x40)
            return False
        self.interrupt_music();self.activities.game_open=False
        self.drag_anchor=None;user32.ReleaseCapture()
        self.motion.enter('idle');self.particles.clear();self.speech=''
        self.hidden=True;self.hidden_at=time.monotonic()
        self.tray.set_hidden(True);self.save()
        user32.ShowWindow(self.hwnd,0)
        user32.SetTimer(self.hwnd,1,1000,None)
        self.write_diagnostics(self.hidden_at)
        return True

    def show_from_tray(self):
        now=time.monotonic()
        if self.hidden:
            paused=max(0.,now-self.hidden_at)
            self.hidden=False
            self.next_blink+=paused;self.next_talk+=paused;self.next_expression+=paused
            if self.activities.rest_due:self.activities.rest_due+=paused
            self.last_tick=now;self.blink_until=0
            self.pose_mixer.reset();self.clamp()
            self.speech='喵帕斯～咱回来啦。';self.speech_until=now+3
            self.voice_line('greet')
            if self.tray:self.tray.set_hidden(False)
            user32.SetTimer(self.hwnd,1,15,None)
            if self.surface:
                image,_=self.render(now);self.surface.show(self.hwnd,image,self.x,self.y)
            user32.ShowWindow(self.hwnd,4);self.zorder()
            self.write_diagnostics(now)
        user32.SetForegroundWindow(self.hwnd)

    def tray_menu(self):
        menu=user32.CreatePopupMenu();self.in_menu=True
        user32.AppendMenuW(menu,0,1,'叫莲儿出来' if self.hidden else '收纳进系统托盘')
        user32.AppendMenuW(menu,0x800,0,None)
        user32.AppendMenuW(menu,0,99,'完全退出')
        x,y=cursor();user32.SetForegroundWindow(self.hwnd)
        try:command=user32.TrackPopupMenu(menu,0x102,x,y,0,self.hwnd,None)
        finally:
            user32.DestroyMenu(menu);self.in_menu=False
            user32.PostMessageW(self.hwnd,0,0,0)
        if command==1:
            self.show_from_tray() if self.hidden else self.hide_to_tray()
        elif command==99:self.exit_app()

    def exit_app(self):
        user32.DestroyWindow(self.hwnd)

    def write_diagnostics(self,now,image=None):
        if not self.args.diagnostics:return
        if image is not None:self.last_alpha=image.getchannel('A').getextrema()
        state={'state':self.motion.state,'walking':self.walking,'x':round(self.x),'y':round(self.y),
               'size':self.size,'speech':self.speech,'frames':self.frames,'elapsed':round(now-self.started,3),
               'alpha':getattr(self,'last_alpha',(0,255)),'atlas_frame':self.motion.frame(),
               'audio_playing':self.audio_playing,'audio_starts':self.audio_starts,'direction':self.motion.direction,
               'renderer':'open-source-v1.0.0','pose_sample':self.motion.sample(),
               'voice_enabled':self.voice_enabled,'voice_volume':self.voice_volume,'voice_count':len(self.voices.clips),
               'voice_playing':self.voice_player.playing,'voice_starts':self.voice_player.starts,
               'voice_completions':self.voice_player.completions,'voice_clip':self.voice_player.last_clip,'voice_error':self.voice_player.last_error,
               'track':self.selected_track,'track_title':self.active_track.title,'music_mode':self.music_mode,
               'music_count':len(self.music.tracks),'volume':self.volume,'follow':self.activities.follow,
               'affection':self.activities.affection,'game_open':self.activities.game_open,
               'expression':self.motion.expression,'pet_held':self.motion.pet_held,'pounce_stage':self.pounce_stage,
               'hidden':self.hidden,'tray_active':bool(self.tray and self.tray.active),'hwnd':self.hwnd}
        Path(self.args.diagnostics).write_text(json.dumps(state,ensure_ascii=False),encoding='utf-8')
        self.last_diagnostic=now

    def tick(self):
        now = time.monotonic()
        dt = min(now - self.last_tick, .1)
        self.last_tick = now
        self.voice_player.poll()
        if self.hidden:
            self.write_diagnostics(now)
            if self.args.exit_after and now-self.started>=self.args.exit_after:self.exit_app()
            return
        if now > self.next_blink:
            self.blink_until = now + .24
            self.next_blink = now + self.rng.uniform(3.2, 6.8)
        if self.speech and now > self.speech_until:
            self.speech = ""
        if self.head_touch is not None and self.motion.state=='pet' and now>=self.touch_heart_at:
            self.emote(count=1);self.touch_heart_at=now+1.2
        if self.motion.state=='idle' and not self.drag_anchor and self.head_touch is None and not self.activities.game_open and not self.in_menu and now>=self.next_expression:
            self.motion.emote(self.rng.choice((0,0,1,2,4)))
            self.next_expression=now+self.rng.uniform(20,38)
        if not self.quiet and self.motion.state == 'idle' and not self.drag_anchor and not self.activities.game_open and now > self.next_talk:
            self.say()
        if self.activities.follow and not self.in_menu and not self.drag_anchor and not self.activities.game_open and self.motion.state in ('idle','walk'):
            mx,my=cursor()
            area=work_area(self.x+self.width/2,self.y+self.height/2)
            target=max(area.left+self.width/2,min(area.right-self.width/2,mx))
            direction=self.activities.follow_direction(self.x+self.width/2,target,max(75,self.size*.5))
            if not direction:
                if self.motion.state=='walk':self.motion.stop()
            elif self.motion.state=='idle':self.motion.walk(direction)
            elif self.motion.direction!=direction:self.motion.turn()
            else:self.motion.stop_requested=False
        if self.activities.poll(now,self.motion.state=='idle' and not self.activities.game_open and not self.drag_anchor and not self.in_menu):
            self.say('你，咱们让眼睛和肩膀歇一会儿吧。',voice_cue='rest')
        previous=self.motion.state
        pause_walk=self.walking and (self.in_menu or self.drag_anchor)
        distance = self.motion.update(0. if pause_walk else dt)
        self.pounce_events(now)
        if self.motion.state!='pounce' and previous=='pounce':
            self.pounce_stage=0;self.save()
        if previous=='flute_out' and self.motion.state=='idle' and self.music_session:
            if self.music_mode=='repeat':self.play_flute(self.selected_track,True)
            elif self.music_mode=='shuffle':self.next_song()
            else:self.music_session=False
        if distance:
            self.x += distance
            before = self.x
            self.clamp()
            if self.x != before:
                self.motion.turn()
        self.audio_events()
        image, name = self.render(now)
        self.surface.show(self.hwnd, image, self.x, self.y)
        self.frames += 1
        if self.args.diagnostics and now - self.last_diagnostic > .5:
            self.write_diagnostics(now,image)
        if self.args.exit_after and now - self.started >= self.args.exit_after:
            user32.DestroyWindow(self.hwnd)

    def window_proc(self, hwnd, message, wparam, lparam):
        try:
            if message==RESTORE_MESSAGE:
                self.show_from_tray();return 0
            if message==TRAY_MESSAGE and self.tray:
                event=self.tray.event(lparam)
                if event=='show':self.show_from_tray()
                elif event=='menu':self.tray_menu()
                return 0
            if self.taskbar_message and message==self.taskbar_message and self.tray:
                self.tray.add();self.tray.set_hidden(self.hidden);return 0
            if message == 0x113:  # WM_TIMER
                self.tick()
                return 0
            if message == 0x201:  # WM_LBUTTONDOWN
                mx, my = cursor()
                if self.head_hit(mx-self.x,my-self.y):
                    self.pet_head(held=True)
                    self.head_touch=(mx,my)
                    user32.SetCapture(hwnd)
                    return 0
                self.drag_anchor = (mx, my, self.x, self.y)
                self.dragged = False
                user32.SetCapture(hwnd)
                return 0
            if message == 0x200 and self.head_touch is not None:
                mx,my=cursor();last_x,last_y=self.head_touch
                # Stroking advances the gentle rub rather than dragging the pet.
                if self.motion.state=='pet':self.motion.age+=min(.06,abs(mx-last_x)/max(1,self.size)*.2)
                self.head_touch=(mx,my)
                return 0
            if message == 0x200 and self.drag_anchor:  # WM_MOUSEMOVE
                mx, my = cursor()
                start_x, start_y, origin_x, origin_y = self.drag_anchor
                if abs(mx - start_x) + abs(my - start_y) > 5:
                    self.dragged = True
                if self.dragged:
                    if self.motion.state != 'drag':
                        self.interrupt_music();self.activities.game_open=False
                        self.motion.drag()
                        self.audio_events()
                    self.x, self.y = origin_x + mx - start_x, origin_y + my - start_y
                    self.clamp()
                return 0
            if message == 0x202:  # WM_LBUTTONUP
                if self.head_touch is not None:
                    self.end_head_touch();user32.ReleaseCapture();return 0
                if self.drag_anchor:
                    user32.ReleaseCapture()
                    self.drag_anchor = None
                    if not self.dragged:
                        mx,my=cursor()
                        self.on_click(mx-self.x,my-self.y)
                    else:
                        self.motion.enter('idle')
                        self.save()
                return 0
            if message == 0x215:  # WM_CAPTURECHANGED
                self.end_head_touch()
                self.drag_anchor = None
                if self.motion.state == 'drag':
                    self.motion.enter('idle')
                return 0
            if message == 0x203:  # WM_LBUTTONDBLCLK
                mx,my=cursor()
                if self.head_hit(mx-self.x,my-self.y):
                    self.pet_head(held=True);self.head_touch=(mx,my);user32.SetCapture(hwnd);return 0
                self.interrupt_music();self.activities.game_open=False
                self.say("喵帕斯～你！", True)
                return 0
            if message == 0x205:  # WM_RBUTTONUP
                self.menu()
                return 0
            if message == 0x100:  # WM_KEYDOWN, local to this window
                if wparam == 0x1B:
                    self.hide_to_tray()
                elif wparam==0x51 and user32.GetKeyState(0x11)&0x8000:
                    self.exit_app()
                elif wparam == 0x20:
                    self.toggle_sleep()
                elif wparam == 0x70:
                    self.say("喵帕斯～你，咱在这里。", True)
                elif wparam == 0x71:
                    self.play_flute()
                elif wparam == 0x72:self.next_song()
                elif wparam == 0x73:self.toggle_follow()
                elif wparam == 0x74:self.open_game()
                elif wparam == 0x75:self.feed()
                elif wparam == 0x76:self.start_pounce()
                elif wparam == 0x77:self.show_expression()
                elif wparam == 0x78:self.toggle_voice()
                return 0
            if message in (0x7E, 0x1A):  # display / working-area change
                self.clamp()
                return 0
            if message == 0x10:  # WM_CLOSE
                self.hide_to_tray()
                return 0
            if message == 0x2:  # WM_DESTROY
                user32.KillTimer(hwnd, 1)
                self.voice_player.close()
                if self.tray:self.tray.close()
                winsound.PlaySound(None, 0)
                self.save()
                user32.PostQuitMessage(0)
                return 0
        except Exception:
            logging.exception("Window message failed: %s", message)
            if message == 0x113:
                user32.KillTimer(hwnd, 1)
                user32.MessageBoxW(hwnd, "桌宠运行遇到错误，请查看同目录的 errors.log。", TITLE, 0x10)
                user32.DestroyWindow(hwnd)
                return 0
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def run(self):
        instance = kernel32.GetModuleHandleW(None)
        self.callback = WNDPROC(self.window_proc)
        icon_path = RESOURCES / "assets" / "renge.ico"
        icon = user32.LoadImageW(None, str(icon_path), 1, 32, 32, 0x10) if icon_path.exists() else None
        cls = WNDCLASS(0x8, self.callback, 0, 0, instance, icon,
                       user32.LoadCursorW(None, C.c_void_p(32649)), None, None, "RengeDesktopPetOpenSourceWindowV1")
        if not user32.RegisterClassW(C.byref(cls)):
            raise C.WinError(C.get_last_error())
        self.hwnd = user32.CreateWindowExW(0x80000 | 0x40000, cls.class_name, TITLE, 0x80000000,
                                          round(self.x), round(self.y), self.width, self.height,
                                          None, None, instance, None)
        if not self.hwnd:
            raise C.WinError(C.get_last_error())
        self.surface = LayeredSurface(self.width, self.height)
        self.taskbar_message=user32.RegisterWindowMessageW('TaskbarCreated')
        self.tray=TrayIcon(self.hwnd,icon_path)
        self.zorder()
        self.say(greeting(datetime.now().hour)+' 右键可以点歌、一起玩。', True)
        if self.args.start_state == 'walk':
            self.motion.walk(1)
        elif self.args.start_state == 'flute':
            self.play_flute()
        elif self.args.start_state == 'sleep':
            self.motion.sleep()
        elif self.args.start_state == 'pounce':self.start_pounce()
        elif self.args.start_state == 'pet':self.pet_head()
        elif self.args.start_state == 'emote':self.show_expression(1)
        self.tick()
        user32.ShowWindow(self.hwnd, 4)  # SW_SHOWNOACTIVATE: do not steal keyboard focus.
        if not user32.SetTimer(self.hwnd, 1, 15, None):
            raise C.WinError(C.get_last_error())
        msg = W.MSG()
        try:
            while True:
                result = user32.GetMessageW(C.byref(msg), None, 0, 0)
                if result == -1:
                    raise C.WinError(C.get_last_error())
                if result == 0:
                    break
                user32.TranslateMessage(C.byref(msg))
                user32.DispatchMessageW(C.byref(msg))
        finally:
            self.voice_player.close()
            if self.tray:self.tray.close()
            self.surface.close()


def main():
    parser = argparse.ArgumentParser(description=TITLE)
    parser.add_argument("--diagnostics", help=argparse.SUPPRESS)
    parser.add_argument("--exit-after", type=float, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--start-state", choices=('idle', 'walk', 'flute', 'sleep','pounce','pet','emote'), default='idle', help=argparse.SUPPRESS)
    parser.add_argument('--track',help=argparse.SUPPRESS)
    parser.add_argument('--settings-file',help=argparse.SUPPRESS)
    args = parser.parse_args()
    logging.basicConfig(filename=BASE / "errors.log", level=logging.ERROR,
                        format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8")
    try:
        user32.SetProcessDpiAwarenessContext(C.c_void_p(-4))
    except AttributeError:
        user32.SetProcessDPIAware()
    mutex = kernel32.CreateMutexW(None, False, "Local\\RengeDesktopPet.OpenSourceV1")
    if C.get_last_error() == 183:
        for _ in range(30):
            hwnd=user32.FindWindowW('RengeDesktopPetOpenSourceWindowV1',None)
            if hwnd:
                user32.PostMessageW(hwnd,RESTORE_MESSAGE,0,0)
                break
            time.sleep(.05)
        kernel32.CloseHandle(mutex)
        return
    try:
        Pet(args).run()
    except Exception:
        logging.exception("Startup failed")
        user32.MessageBoxW(None, "启动失败，请查看同目录的 errors.log。", TITLE, 0x10)
        raise
    finally:
        if mutex:
            kernel32.CloseHandle(mutex)


if __name__ == "__main__":
    main()
