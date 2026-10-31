"""Offline original voice clips and non-blocking, per-app PCM playback."""
from array import array
import ctypes as C
from ctypes import wintypes as W
from dataclasses import dataclass
import json
import logging
from pathlib import Path
import random
import threading
import wave


@dataclass(frozen=True)
class VoiceClip:
    id: str
    path: Path
    cues: tuple
    subtitle: str
    duration: float


def read_pcm(path):
    with wave.open(str(path),'rb') as source:
        if source.getcomptype()!='NONE' or source.getsampwidth()!=2 or source.getnchannels() not in (1,2):
            raise ValueError('语音需要单声道或双声道 PCM16 WAV')
        rate=source.getframerate();channels=source.getnchannels()
        if not 8000<=rate<=48000:raise ValueError('语音采样率需为 8–48 kHz')
        duration=source.getnframes()/rate
        if not 0<duration<=15:raise ValueError('语音片段需在 15 秒以内')
        return source.readframes(source.getnframes()),rate,channels,duration


class VoiceLibrary:
    def __init__(self,resources,base):
        self.resources=Path(resources);self.base=Path(base)
        self.clips=[];self.last_id=None
        self.reload()

    def reload(self):
        clips=[]
        root=self.resources/'assets'/'voice'
        manifest=root/'clips.json'
        if manifest.exists():
            for entry in json.loads(manifest.read_text(encoding='utf-8'))['clips']:
                path=(root/entry['file']).resolve()
                if not path.is_relative_to(root.resolve()):continue
                try:
                    _,_,_,duration=read_pcm(path)
                    clips.append(VoiceClip(entry['id'],path,tuple(entry['cues']),entry['subtitle'],duration))
                except (OSError,ValueError,wave.Error,EOFError):logging.exception('Voice clip unavailable: %s',entry['id'])
        self.custom=self.base/'voices';self.custom.mkdir(exist_ok=True)
        cue_names={'打招呼':'greet','闲聊':'talk','摸头':'pet','喂糖':'feed','飞扑':'pounce',
            '起床':'wake','睡觉':'sleep','跟随':'follow','停下':'stop','好奇':'curious','开心':'happy','休息':'rest'}
        for path in sorted(self.custom.glob('*.wav')):
            prefix=path.stem.split('-',1)[0]
            cue=cue_names.get(prefix,prefix)
            if cue not in set(cue_names.values()):continue
            try:
                _,_,_,duration=read_pcm(path)
                clips.append(VoiceClip('custom-'+path.stem,path,(cue,),path.stem.partition('-')[2] or '（原声短句）',duration))
            except (OSError,ValueError,wave.Error,EOFError):continue
        self.clips=clips

    def choose(self,cue,rng=None):
        options=[c for c in self.clips if cue in c.cues]
        custom=[c for c in options if c.id.startswith('custom-')]
        options=custom or options
        if not options:return None
        choices=[c for c in options if c.id!=self.last_id] or options
        clip=(rng or random).choice(choices);self.last_id=clip.id
        return clip


class WAVEFORMATEX(C.Structure):
    _pack_=2
    _fields_=[('wFormatTag',W.WORD),('nChannels',W.WORD),('nSamplesPerSec',W.DWORD),
        ('nAvgBytesPerSec',W.DWORD),('nBlockAlign',W.WORD),('wBitsPerSample',W.WORD),('cbSize',W.WORD)]


class WAVEHDR(C.Structure):
    _fields_=[('lpData',C.c_void_p),('dwBufferLength',W.DWORD),('dwBytesRecorded',W.DWORD),
        ('dwUser',C.c_size_t),('dwFlags',W.DWORD),('dwLoops',W.DWORD),('lpNext',C.c_void_p),('reserved',C.c_size_t)]


class WaveOutput:
    """Keep the PCM buffer alive until waveOut signals completion or reset."""
    def __init__(self):
        self.api=C.WinDLL('winmm')
        for name,args in {
            'waveOutOpen':(C.POINTER(W.HANDLE),W.UINT,C.POINTER(WAVEFORMATEX),C.c_size_t,C.c_size_t,W.DWORD),
            'waveOutPrepareHeader':(W.HANDLE,C.POINTER(WAVEHDR),W.UINT),
            'waveOutWrite':(W.HANDLE,C.POINTER(WAVEHDR),W.UINT),
            'waveOutUnprepareHeader':(W.HANDLE,C.POINTER(WAVEHDR),W.UINT),
            'waveOutReset':(W.HANDLE,), 'waveOutClose':(W.HANDLE,)}.items():
            fn=getattr(self.api,name);fn.argtypes=args;fn.restype=W.UINT
        self.handle=None;self.header=None;self.buffer=None
        self.starts=0;self.completions=0;self.last_clip=None;self.last_error=''

    @staticmethod
    def scaled_pcm(pcm,volume):
        volume=max(0,min(100,int(volume)))
        if volume==100:return pcm
        return array('h',(round(v*volume/100) for v in array('h',pcm))).tobytes()

    @property
    def playing(self):
        return self.handle is not None and self.header is not None and not self.header.dwFlags&1

    def poll(self):
        if self.handle is not None and self.header.dwFlags&1:
            if self.stop():self.completions+=1

    def stop(self):
        if self.handle is None:return True
        code=self.api.waveOutReset(self.handle)
        if code:
            self.last_error=f'waveOutReset: {code}';return False
        code=self.api.waveOutUnprepareHeader(self.handle,C.byref(self.header),C.sizeof(WAVEHDR))
        if code:
            self.last_error=f'waveOutUnprepareHeader: {code}';return False
        code=self.api.waveOutClose(self.handle)
        if code:
            self.last_error=f'waveOutClose: {code}';return False
        self.handle=self.header=self.buffer=None
        return True

    def play(self,clip,volume,cancelled=lambda:False):
        if not self.stop():return False
        try:
            pcm,rate,channels,_=read_pcm(clip.path)
            pcm=self.scaled_pcm(pcm,volume)
            fmt=WAVEFORMATEX(1,channels,rate,rate*channels*2,channels*2,16,0)
            handle=W.HANDLE()
            code=self.api.waveOutOpen(C.byref(handle),0xffffffff,C.byref(fmt),0,0,0)
            if code:raise OSError(f'waveOutOpen: {code}')
            self.handle=handle;self.buffer=C.create_string_buffer(pcm)
            self.header=WAVEHDR(C.cast(self.buffer,C.c_void_p),len(pcm),0,0,0,0,None,0)
            code=self.api.waveOutPrepareHeader(handle,C.byref(self.header),C.sizeof(WAVEHDR))
            if code:
                self.api.waveOutClose(handle);self.handle=self.header=self.buffer=None
                raise OSError(f'waveOutPrepareHeader: {code}')
            if cancelled():self.stop();return False
            code=self.api.waveOutWrite(handle,C.byref(self.header),C.sizeof(WAVEHDR))
            if code:raise OSError(f'waveOutWrite: {code}')
            self.starts+=1;self.last_clip=clip.id;self.last_error=''
            return True
        except (OSError,ValueError,wave.Error,EOFError) as error:
            self.last_error=str(error);self.stop()
            logging.exception('Voice playback failed')
            return False


class VoicePlayer:
    """Latest request wins; all device calls stay off the animation thread."""
    def __init__(self):
        self.output=WaveOutput()
        self.condition=threading.Condition()
        self.pending=None;self.generation=0;self.loading=False
        self.stop_requested=False;self.closed=False;self.worker=None

    @property
    def playing(self):
        with self.condition:return self.pending is not None or self.loading or self.output.playing

    @property
    def starts(self):return self.output.starts
    @property
    def completions(self):return self.output.completions
    @property
    def last_clip(self):return self.output.last_clip
    @property
    def last_error(self):return self.output.last_error

    def play(self,clip,volume):
        with self.condition:
            if self.closed:return False
            self.generation+=1;self.pending=(self.generation,clip,volume)
            if self.worker is None:
                self.worker=threading.Thread(target=self._run,name='RengeVoice',daemon=True)
                self.worker.start()
            self.condition.notify()
        return True

    def stop(self):
        with self.condition:
            self.generation+=1;self.pending=None;self.stop_requested=True
            self.condition.notify()
        return True

    def poll(self):pass  # The worker owns header completion and device cleanup.

    def close(self,wait=False):
        with self.condition:
            self.closed=True;self.generation+=1;self.pending=None
            self.stop_requested=True;self.condition.notify()
        if wait and self.worker is not None:self.worker.join(timeout=3)

    def _run(self):
        while True:
            with self.condition:
                if not self.closed and self.pending is None and not self.stop_requested:
                    self.condition.wait(timeout=.015 if self.output.handle else None)
                job=self.pending;self.pending=None
                stop=self.stop_requested;self.stop_requested=False
                closed=self.closed;self.loading=job is not None
            if stop or closed:self.output.stop()
            if closed:return
            if job is not None:
                generation,clip,volume=job
                self.output.play(clip,volume,lambda:self.generation!=generation)
                with self.condition:self.loading=False
            self.output.poll()
