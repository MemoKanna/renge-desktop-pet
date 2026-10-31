"""Offline recorder-like synthesis from a monophonic note timeline."""
from array import array
import math
from pathlib import Path
import random
import wave


def write_wave(path, events, rate=22050):
    duration=max(start+length for start,length,pitch in events)+.3
    samples=array('h',[0])*round(duration*rate)
    noise=random.Random(17)
    for start,length,pitch in events:
        if not pitch:continue
        offset=round(start*rate)
        sounding=max(.04,length-min(.055,length*.10))
        frequency=440*2**((pitch-69)/12)
        for i in range(round(sounding*rate)):
            t=i/rate
            envelope=max(0.,min(1.,t/.028,(sounding-t)/.06))
            envelope*=.86+.14*math.exp(-t*4)
            phase=math.tau*frequency*t+.009*math.sin(math.tau*4.2*t)
            value=math.sin(phase)+.10*math.sin(phase*2)+.025*math.sin(phase*3)+noise.uniform(-.006,.006)
            index=offset+i
            samples[index]=max(-32767,min(32767,samples[index]+round(32767*.19*envelope*value)))
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with wave.open(str(path),'wb') as output:
        output.setnchannels(1);output.setsampwidth(2);output.setframerate(rate)
        output.writeframes(samples.tobytes())
    return duration
