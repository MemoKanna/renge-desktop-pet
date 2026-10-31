"""Local playlist, note-aligned finger poses and per-app PCM volume."""
from array import array
from bisect import bisect_right
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import wave


@dataclass
class Track:
    id: str
    title: str
    path: Path
    duration: float
    events: list

    def finger_pose(self, seconds):
        if not self.events:return None
        starts=[e[0] for e in self.events]
        i=bisect_right(starts,seconds)-1
        if i<0:return 'flute',6,6,0.,False
        t,d,p=self.events[i]
        if seconds>t+d:return 'flute',6,6,0.,False
        target=3+(p%3)
        previous=3+(self.events[i-1][2]%3) if i else 3
        return 'flute',previous,target,min(1.,max(0.,(seconds-t)/.09)),False


class MusicLibrary:
    def __init__(self, resources, base):
        self.resources=Path(resources)
        self.base=Path(base)
        self.tracks=[]
        self.reload()

    def reload(self):
        tracks=[]
        directory=self.resources/'assets'/'music'
        for item in json.loads((directory/'tracks.json').read_text(encoding='utf-8')):
            path=directory/item['file']
            with wave.open(str(path),'rb') as source:
                duration=source.getnframes()/source.getframerate()
            tracks.append(Track(item['id'],item['title'],path,duration,item.get('events',[])))
        custom=self.base/'music'
        custom.mkdir(exist_ok=True)
        for path in sorted(custom.glob('*.wav')):
            try:
                with wave.open(str(path),'rb') as source:
                    if source.getsampwidth()!=2 or source.getcomptype()!='NONE':continue
                    duration=source.getnframes()/source.getframerate()
                if 0<duration<=600:
                    identity='custom-'+hashlib.sha1(path.name.encode('utf-8')).hexdigest()[:12]
                    tracks.append(Track(identity,path.stem+' · 自定义',path,duration,[]))
            except (OSError,wave.Error,EOFError):continue
        self.tracks=tracks

    def get(self, identity):
        return next((t for t in self.tracks if t.id==identity),self.tracks[0])

    def playback_path(self, track, volume):
        volume=max(0,min(100,int(volume)))
        if volume==100:return track.path
        cache=self.base/'data'/'audio-cache'
        cache.mkdir(parents=True,exist_ok=True)
        signature=hashlib.sha256(track.path.read_bytes()).hexdigest()+':'+str(volume)
        key=hashlib.sha256(signature.encode('utf-8')).hexdigest()[:20]
        destination=cache/(key+'.wav')
        if not destination.exists():
            with wave.open(str(track.path),'rb') as source:
                parameters=source.getparams()
                if source.getsampwidth()!=2:raise ValueError('需要 PCM16 WAV')
                values=array('h',source.readframes(source.getnframes()))
            values=array('h',(round(value*volume/100) for value in values))
            with wave.open(str(destination),'wb') as output:
                output.setparams(parameters);output.writeframes(values.tobytes())
        return destination
