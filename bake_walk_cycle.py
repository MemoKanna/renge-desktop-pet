"""Rebuild cached walking poses after editing walk_rig.py or the rig textures."""
from pathlib import Path
import json
from PIL import Image
from walk_rig import WalkRig, CYCLE_VERSION

assets=Path(__file__).resolve().parent/'assets'
rig=WalkRig(assets,use_cycle=False)
sheet=Image.new('RGBA',(4800,2240))
for i in range(128):
    sheet.alpha_composite(rig.render_procedural(i/128,250),((i%16)*300,(i//16)*280))
sheet.save(assets/'walk-cycle.png')
(assets/'walk-cycle.json').write_text(json.dumps({'version':CYCLE_VERSION,'count':128,'columns':16,'cell':[300,280]},indent=2),encoding='utf-8')
print('Rebuilt 128 cached walking poses.')
