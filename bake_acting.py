"""Rebuild smoothly sampled action atlases from the existing cutout rig."""
from pathlib import Path
import argparse
import json
import math
from PIL import Image
from walk_rig import WalkRig
from action_rig import ActionRig,VERSION,PET_DURATION,POUNCE_DURATION

def main():
    parser=argparse.ArgumentParser();selection=parser.add_mutually_exclusive_group()
    selection.add_argument('--only-pounce',action='store_true');selection.add_argument('--only-rest',action='store_true');args=parser.parse_args()
    directory=Path(__file__).resolve().parent/'assets'
    actor=ActionRig(directory,WalkRig(directory),use_cache=False)
    data={'version':VERSION,'actions':{}}
    jobs=[('pet',PET_DURATION,40,0),('pounce',POUNCE_DURATION,60,0)]
    jobs.extend(('emote',3.6,12,index) for index in range(8))
    if args.only_pounce or args.only_rest:
        previous=json.loads((directory/'acting-cycle.json').read_text(encoding='utf-8'))
        compatible=('acting-7.2-sleeve-volume',VERSION) if args.only_rest else (VERSION,)
        if previous['version'] not in compatible:raise ValueError('Full rebuild required for this source version')
        data['actions']=previous['actions']
        jobs=[job for job in jobs if (job[0]!='pounce' if args.only_rest else job[0]=='pounce')]
    for kind,duration,fps,index in jobs:
        key=f'emote-{index}' if kind=='emote' else kind
        count=round(duration*fps)+1;cols=12;cell=(300,280)
        sheet=Image.new('RGBA',(cell[0]*cols,cell[1]*math.ceil(count/cols)))
        for i in range(count):
            image=actor.procedural(kind,min(duration,i/fps),250,index)
            box=image.getchannel('A').point(lambda a:255 if a>80 else 0).getbbox()
            if box is None or box[0]<1 or box[1]<1 or box[2]>=cell[0]-1 or box[3]>=cell[1]-1:
                raise ValueError(f'Clipped action {key}/{i}: {box}')
            sheet.alpha_composite(image,((i%cols)*cell[0],(i//cols)*cell[1]))
        filename=f'acting-{key}.png';sheet.save(directory/filename,optimize=True)
        data['actions'][key]={'file':filename,'cell':cell,'columns':cols,'count':count,'fps':fps,'duration':duration}
        print(f'{key}: {count} poses',flush=True)
    (directory/'acting-cycle.json').write_text(json.dumps(data,indent=2),encoding='utf-8')
if __name__=='__main__':main()
