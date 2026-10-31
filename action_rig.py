"""Continuous cutout acting using the existing, approved walk artwork.

Expression artwork is generated separately. Only the eye/mouth interiors are
registered onto the canonical scalp, so neither antenna nor tails can pop.
"""
from functools import lru_cache
from pathlib import Path
import json
import math
from PIL import Image, ImageDraw, ImageFilter, ImageOps, ImageChops

NAMES = ('normal', 'curious', 'content', 'pat', 'unimpressed', 'serious', 'surprised', 'knee')
LABELS = ('认真发呆', '咦，是什么', '淡淡开心', '舒服眯眼', '半眯眼', '认真起来', '小小惊讶', '膝盖呀')
VERSION = 'acting-7.3-rest-arms'
CANVAS = (600, 560)
PET_DURATION = 3.8
POUNCE_DURATION = 5.8
LEG_LENGTH = 45.
NECK = (282., 295.)
UPPER_ARM = 50.
FOREARM = 40.


def ease(t):
    t = max(0., min(1., t))
    return t*t*(3-2*t)


def lerp(a, b, t):
    if isinstance(a, (tuple, list)):
        return tuple(lerp(x,y,t) for x,y in zip(a,b))
    return a+(b-a)*t


def keys(age, timeline):
    if age <= timeline[0][0]: return timeline[0][1]
    for (a, x), (b, y) in zip(timeline, timeline[1:]):
        if age <= b: return lerp(x,y,ease((age-a)/(b-a)))
    return timeline[-1][1]


def pounce_travel(age):
    """Normalized forward travel: acceleration, flight, dissipating slide."""
    return flow(age, ((0,0),(.48,0),(1.10,.60),(1.65,.90),(2.25,1),(POUNCE_DURATION,1)))


def flow(age, timeline):
    """Monotone cubic Hermite: intermediate keys do not stop the body."""
    if age<=timeline[0][0]:return timeline[0][1]
    if age>=timeline[-1][0]:return timeline[-1][1]
    spans=[b[0]-a[0] for a,b in zip(timeline,timeline[1:])]
    slopes=[(b[1]-a[1])/span for a,b,span in zip(timeline,timeline[1:],spans)]
    tangent=[0.]
    for i in range(1,len(timeline)-1):
        a,b=slopes[i-1],slopes[i]
        if a*b<=0:tangent.append(0.)
        else:
            w1=2*spans[i]+spans[i-1];w2=spans[i]+2*spans[i-1]
            tangent.append((w1+w2)/(w1/a+w2/b))
    tangent.append(0.)
    for i,((a,x),(b,y)) in enumerate(zip(timeline,timeline[1:])):
        if age<=b:
            t=(age-a)/(b-a)
            return (2*t**3-3*t*t+1)*x+(t**3-2*t*t+t)*(b-a)*tangent[i]+(-2*t**3+3*t*t)*y+(t**3-t*t)*(b-a)*tangent[i+1]


def leg_joints(hip, upper_angle, lower_angle):
    """FK with fixed bone lengths, including crouch, flight and sitting."""
    a,b=map(math.radians,(upper_angle,lower_angle))
    knee=(hip[0]+LEG_LENGTH*math.sin(a),hip[1]+LEG_LENGTH*math.cos(a))
    ankle=(knee[0]+LEG_LENGTH*math.sin(b),knee[1]+LEG_LENGTH*math.cos(b))
    return hip,knee,ankle


def arm_joints(shoulder,target,side):
    """Reach a wrist with two fixed bones and a stable elbow bend."""
    dx,dy=target[0]-shoulder[0],target[1]-shoulder[1]
    distance=max(1e-9,math.hypot(dx,dy));ux,uy=dx/distance,dy/distance
    distance=max(UPPER_ARM-FOREARM+.3,min(UPPER_ARM+FOREARM-.3,distance))
    wrist=(shoulder[0]+ux*distance,shoulder[1]+uy*distance)
    along=(UPPER_ARM**2-FOREARM**2+distance**2)/(2*distance)
    height=math.sqrt(max(0.,UPPER_ARM**2-along**2));sign=-1 if side=='near' else 1
    elbow=(shoulder[0]+ux*along+sign*uy*height,shoulder[1]+uy*along-sign*ux*height)
    return shoulder,elbow,wrist


class ActionRig:
    def __init__(self, directory, rig, use_cache=True):
        self.rig=rig
        self.directory=Path(directory)
        self.heads=self.expression_heads()
        # The isolated torso contains a cut-end neck outline. Occlude this
        # artificial top edge; the connected head supplies the actual neck.
        self.torso=rig.parts['torso'].copy()
        cut=Image.new('L',self.torso.size,255)
        ImageDraw.Draw(cut).polygon(((87,0),(153,0),(153,8),(90,10)),fill=0)
        self.torso.putalpha(ImageChops.multiply(self.torso.getchannel('A'),cut.filter(ImageFilter.GaussianBlur(.8))))
        # Remove the separate shoe texture's square sock stub. The shin now
        # owns the full sock; shoe pivot sits at the shoe opening.
        self.shoes={side:rig.parts[side+'_shoe'].crop((0,round(rig.parts[side+'_shoe'].height*.45),rig.parts[side+'_shoe'].width,rig.parts[side+'_shoe'].height)) for side in ('far','near')}
        face=rig.layout['head_face'];sy=192/((face[1]+face[3])/2);sx=80/(face[2]-face[0])
        self.neck_pivot=((212*sx+10)/self.heads[0].width,316*sy/412)
        self.neck_texture=rig.parts['head'].crop((204,294,222,305))
        # The torso artwork still contains downward sleeve silhouettes.
        # Keep the jacket panel and skirt, and let the articulated arms own
        # the sleeves during the complete flight action.
        self.flight_torso=self.torso.copy()
        body=Image.new('L',self.torso.size)
        outline=((48,0),(191,0),(191,36),(172,72),(193,151),(208,176),
                 (239,186),(239,245),(0,245),(0,186),(30,176),(44,151),(66,72),(48,36))
        ImageDraw.Draw(body).polygon(outline,fill=255)
        self.flight_torso.putalpha(ImageChops.multiply(self.torso.getchannel('A'),body.filter(ImageFilter.GaussianBlur(.8))))
        self.rest_torso=self.torso.copy()
        body=Image.new('L',self.torso.size)
        ImageDraw.Draw(body).polygon(((48,0),(191,0),(203,60),(207,140),(208,176),
            (239,186),(239,245),(0,245),(0,186),(30,176),(44,151),(66,72),(48,36)),fill=255)
        self.rest_torso.putalpha(ImageChops.multiply(self.torso.getchannel('A'),body.filter(ImageFilter.GaussianBlur(.8))))
        self.sleeves={};self.hands={};self.hand_splits={}
        for side in ('far','near'):
            image=rig.parts[side+'_arm'];start=round(image.height*.8)
            for y in range(round(image.height*.64),round(image.height*.94)):
                pixels=[image.getpixel((x,y)) for x in range(image.width) if image.getpixel((x,y))[3]>180]
                skin=sum(r>210 and g>190 and b>150 and r-g<48 for r,g,b,a in pixels)
                if pixels and skin/len(pixels)>.55:start=y;break
            self.hand_splits[side]=start
            self.sleeves[side]=image.crop((0,0,image.width,start+3))
            self.hands[side]=image.crop((0,max(0,start-2),image.width,image.height))
        self.cache=None
        path=self.directory/'acting-cycle.json'
        if use_cache and path.exists():
            data=json.loads(path.read_text(encoding='utf-8'))
            if data.get('version')==VERSION:
                self.cache=data['actions']

    def expression_heads(self):
        sheet=Image.open(self.directory/'expressions.png').convert('RGBA')
        # Measured pupils from the generated atlas. Register both eye centres,
        # then use small feathered face-interior patches, never generated hair.
        pupils=((227,310,276),(208,290,275),(202,282,276),(185,269,280),
                (226,308,263),(208,289,265),(199,281,258),(180,262,272))
        mouths=((269,327),(246,327),(237,324),(225,324),(267,310),(247,309),(238,311),(220,314))
        raw=self.rig.parts['head']
        results=[]
        for index, ((left,right,y),(mx,my)) in enumerate(zip(pupils,mouths)):
            tile=sheet.crop(((index%4)*384,(index//4)*512,(index%4+1)*384,(index//4+1)*512))
            head=raw.copy()
            sx=(right-left)/72.
            sy=.92
            eyes=tile.transform(raw.size,Image.Transform.AFFINE,(sx,0,left-216*sx,0,sy,y-222*sy),Image.Resampling.BICUBIC)
            mask=Image.new('L',raw.size);d=ImageDraw.Draw(mask)
            d.ellipse((192,198,238,246),fill=255)
            d.ellipse((274,201,311,245),fill=255)
            mask=mask.filter(ImageFilter.GaussianBlur(1.1))
            head=Image.composite(eyes,head,mask)
            mouth=tile.transform(raw.size,Image.Transform.AFFINE,(1.1,0,mx-254*1.1,0,1.05,my-272*1.05),Image.Resampling.BICUBIC)
            mask=Image.new('L',raw.size);ImageDraw.Draw(mask).ellipse((242,262,266,282),fill=255)
            head=Image.composite(mouth,head,mask.filter(ImageFilter.GaussianBlur(2)))
            # The complete alpha and hairstyle remain exactly canonical.
            head.putalpha(raw.getchannel('A'))
            # Remove only the detached neck end cap, keeping nearby lavender
            # bangs. Its skin component is separated by colour, then expanded
            # just enough to include the old black cut-end outline.
            skin=Image.new('L',raw.size)
            for y in range(294,326):
                for x in range(181,259):
                    red,green,blue,alpha=head.getpixel((x,y))
                    if alpha>30 and red>200 and red-blue>15 and green-blue>5:skin.putpixel((x,y),255)
            skin=skin.filter(ImageFilter.MaxFilter(7))
            region=Image.new('L',raw.size);ImageDraw.Draw(region).rectangle((180,294,260,328),fill=255)
            skin=ImageChops.multiply(skin,region).filter(ImageFilter.GaussianBlur(.65))
            for y in range(291,329):
                for x in range(178,262):
                    red,green,blue,alpha=head.getpixel((x,y))
                    if blue>red+3:skin.putpixel((x,y),0)
            head.putalpha(ImageChops.multiply(head.getchannel('A'),ImageChops.invert(skin)))
            face=self.rig.layout['head_face'];cx=(face[0]+face[2])/2;cy=(face[1]+face[3])/2
            sx=80/(face[2]-face[0]);sy=192/cy;cut=min(head.height-20,face[3]+16)
            width=round(head.width*sx);upper=round(cut*sy)
            fitted=Image.new('RGBA',(width+20,412))
            fitted.alpha_composite(head.crop((0,0,head.width,cut)).resize((width,upper),Image.Resampling.LANCZOS),(10,0))
            fitted.alpha_composite(head.crop((0,cut,head.width,head.height)).resize((width,412-upper),Image.Resampling.LANCZOS),(10,upper))
            results.append(fitted)
        return results

    def strip(self, out, image, joints, width, scale):
        """Arc-length strips follow arbitrary bent limbs without round caps."""
        a,b,c=joints
        points=[]
        for i in range(33):
            t=i/32
            # Catmull-style quadratic with the elbow at t=.5.
            control=(2*b[0]-(a[0]+c[0])/2,2*b[1]-(a[1]+c[1])/2)
            points.append(((1-t)**2*a[0]+2*t*(1-t)*control[0]+t*t*c[0],
                           (1-t)**2*a[1]+2*t*(1-t)*control[1]+t*t*c[1]))
        for i,(p,q) in enumerate(zip(points,points[1:])):
            crop=image.crop((0,max(0,round(i/32*image.height)-1),image.width,min(image.height,round((i+1)/32*image.height)+1)))
            dx,dy=q[0]-p[0],q[1]-p[1]
            dimensions=(max(1,round(width*scale)),max(1,round((math.hypot(dx,dy)+2)*scale)))
            # Crop objects are short-lived; resize before paste so the older
            # rig's persistent id(image) cache cannot alias recycled object ids.
            crop=crop.resize(dimensions,Image.Resampling.BICUBIC)
            self.rig.paste_pivot(out,crop,(.5,.5),((p[0]+q[0])/2*scale,(p[1]+q[1])/2*scale),
                math.degrees(math.atan2(dx,dy)),dimensions)

    def leg_layer(self,out,side,joints,scale):
        """Inverse-sample a single texture around two fixed-length bones.

        The nearest-point field makes one continuous skin surface at the
        knee. One mesh pass avoids seams from dozens of overlapping strips.
        Texture length follows bone distance, so socks cannot crawl upwards.
        """
        a,b,c=joints
        u=((b[0]-a[0])/LEG_LENGTH,(b[1]-a[1])/LEG_LENGTH)
        v=((c[0]-b[0])/LEG_LENGTH,(c[1]-b[1])/LEG_LENGTH)
        texture=self.rig.leg_textures[side]
        left=math.floor((min(p[0] for p in joints)-42)*scale)
        top=math.floor((min(p[1] for p in joints)-24)*scale)
        right=math.ceil((max(p[0] for p in joints)+42)*scale)
        bottom=math.ceil((max(p[1] for p in joints)+24)*scale)
        width,height=right-left,bottom-top
        def coords(x,y):
            q=((x+left)/scale,(y+top)/scale)
            candidates=[]
            for start,direction,offset in ((a,u,0.),(b,v,LEG_LENGTH)):
                dx,dy=q[0]-start[0],q[1]-start[1]
                t=max(0.,min(LEG_LENGTH,dx*direction[0]+dy*direction[1]))
                nx,ny=dx-t*direction[0],dy-t*direction[1]
                candidates.append((nx*nx+ny*ny,offset+t,nx*direction[1]-ny*direction[0]))
            distance,along,normal=min(candidates,key=lambda item:item[0])
            transverse=math.copysign(math.sqrt(distance),normal)
            return texture.width/2+transverse,along/(2*LEG_LENGTH)*texture.height
        mesh=[]
        for y in range(0,height,2):
            for x in range(0,width,2):
                x1=min(width,x+2);y1=min(height,y+2)
                mesh.append(((x,y,x1,y1),coords(x,y)+coords(x,y1)+coords(x1,y1)+coords(x1,y)))
        layer=texture.transform((width,height),Image.Transform.MESH,mesh,Image.Resampling.BICUBIC)
        out.alpha_composite(layer,(left,top))

    def arm_layer(self,side,joints,scale,dimensions,cloth_width=None):
        """Sample sleeve length along bones and width perpendicular to them.

        The former y-based quadratic stretched the sleeve sideways at bends.
        A bone-distance UV field preserves the cuff, cloth width and material
        length even when the entire arm points upwards or sideways.
        """
        a,b,c=joints
        texture=self.sleeves[side]
        nominal=(cloth_width if cloth_width is not None else (39. if side=='near' else 37.))*self.rig.width_factors[id(self.rig.parts[side+'_arm'])]
        bones=[]
        for start,end,length,offset in ((a,b,UPPER_ARM,0.),(b,c,FOREARM,UPPER_ARM)):
            bones.append((start,((end[0]-start[0])/length,(end[1]-start[1])/length),length,offset))
        pad=nominal/2+3
        left=math.floor((min(p[0] for p in joints)-pad)*scale)
        top=math.floor((min(p[1] for p in joints)-pad)*scale)
        width=math.ceil((max(p[0] for p in joints)+pad)*scale)-left
        height=math.ceil((max(p[1] for p in joints)+pad)*scale)-top
        def coords(x,y):
            px,py=(x+left)/scale,(y+top)/scale
            candidates=[]
            for index,(start,direction,length,offset) in enumerate(bones):
                dx,dy=px-start[0],py-start[1]
                raw=dx*direction[0]+dy*direction[1]
                t=max(0.,min(length,raw))
                nx,ny=dx-t*direction[0],dy-t*direction[1]
                # Extend UV beyond the shoulder/cuff so rounded source ends
                # remain rounded instead of becoming repeated end rows.
                along=offset+(raw if (index==0 and raw<0) or (index==1 and raw>length) else t)
                sign=dx*direction[1]-dy*direction[0]
                transverse=math.copysign(math.hypot(nx,ny),sign)
                candidates.append((nx*nx+ny*ny,along,transverse))
            _,along,transverse=min(candidates,key=lambda item:item[0])
            return texture.width*(.5+transverse/nominal),texture.height*along/(UPPER_ARM+FOREARM)
        mesh=[]
        for y in range(0,height,2):
            for x in range(0,width,2):
                x1=min(width,x+2);y1=min(height,y+2)
                mesh.append(((x,y,x1,y1),coords(x,y)+coords(x,y1)+coords(x1,y1)+coords(x1,y)))
        sleeve=texture.transform((width,height),Image.Transform.MESH,mesh,Image.Resampling.BICUBIC)
        out=Image.new('RGBA',dimensions)
        hand_angle=math.degrees(math.atan2(c[0]-b[0],c[1]-b[1]))
        self.rig.paste_pivot(out,self.hands[side],(.5,.10),(c[0]*scale,c[1]*scale),hand_angle,(nominal*scale,23*scale))
        out.alpha_composite(sleeve,(left,top))
        return out

    def configuration(self,kind,age,expression=0):
        # All coordinates use the established 500-high design space.
        body_y=0.;tilt=0.;head_tilt=0.;head_dx=0.;head_dy=0.;body_angle=0.;lift=0.
        arms={'far':((321,310),(328,365),(330,416)), 'near':((246,310),(240,365),(239,416))}
        angles={'far':(0.,0.),'near':(0.,0.)}
        if kind=='pet':
            envelope=ease(age/.48)*(1-ease((age-(PET_DURATION-.65))/.65))
            sway=math.sin(max(0,age-.4)*math.tau/1.6)
            head_tilt=(2.5+2*sway)*envelope
            expression=3 if age>.25 and age<PET_DURATION-.3 else 0
            arms={'far':((321,310),(324,366),(311,418)), 'near':((246,310),(239,367),(254,416))}
        elif kind=='emote':
            envelope=ease(age/.4)*(1-ease((age-3.0)/.6))
            head_tilt=(7 if expression==1 else (-2 if expression==4 else 1.5))*envelope
        elif kind=='pounce':
            body_angle=flow(age,((0,0),(.40,-8),(.92,-74),(1.35,-86),(2.05,-85),(2.4,-67),(2.8,-23),(3.2,0),(4.9,0),(POUNCE_DURATION,0)))
            crouch=flow(age,((0,0),(.42,1),(.70,0),(POUNCE_DURATION,0)))
            flight=max(0.,min(1.,(age-.48)/1.10))
            lift=72*4*flight*(1-flight)
            stretch=flow(age,((0,0),(.40,.3),(.85,1),(1.8,1),(2.3,.8),(3.15,0),(POUNCE_DURATION,0)))
            sit=flow(age,((0,0),(2.25,0),(3.2,1),(4.85,1),(POUNCE_DURATION,0)))
            # Animate anatomical rotations, avoiding inward wrist targets
            # that folded the loose sleeve into a hook during recovery.
            arm_angles={
                'near':((0,(-4,-6)),(.4,(-25,-50)),(.95,(-145,-155)),(1.4,(-148,-155)),
                        (1.85,(-70,-105)),(2.35,(-30,-60)),(3.2,(-2,45)),(4.85,(-2,45)),(POUNCE_DURATION,(-4,-6))),
                'far':((0,(7,8)),(.4,(25,50)),(1.,(135,150)),(1.4,(138,150)),
                       (1.85,(70,105)),(2.35,(30,60)),(3.2,(2,-45)),(4.85,(2,-45)),(POUNCE_DURATION,(7,8)))}
            for side in arms:
                rotations=[flow(age,tuple((t,point[axis]) for t,point in arm_angles[side])) for axis in (0,1)]
                rotations[1]+=math.sin(age*6)*1.3*sit*(1 if side=='near' else -1)
                a=arms[side][0];upper,lower=map(math.radians,rotations)
                b=(a[0]+UPPER_ARM*math.sin(upper),a[1]+UPPER_ARM*math.cos(upper))
                c=(b[0]+FOREARM*math.sin(lower),b[1]+FOREARM*math.cos(lower))
                arms[side]=(a,b,c)
            for side in angles:
                air=flow(max(0.,age-(.065 if side=='far' else 0)),((0,0),(.48,0),(.95,1),(1.5,.75),(2.3,.5),(3.2,0),(POUNCE_DURATION,0)))
                upper=30*crouch+(-16 if side=='near' else -6)*air
                lower=-55*crouch+(-66 if side=='near' else -48)*air
                angles[side]=lerp((upper,lower),(62,-22),sit)
            # Pelvis lowers as the planted knees bend, not by stretching legs.
            body_y=(90-LEG_LENGTH*(math.cos(math.radians(30*crouch))+math.cos(math.radians(-55*crouch))))*(1-ease((age-.48)/.22))
            body_y+=26*sit
            expression=5 if age<1.5 else (7 if age<5.1 else 0)
            head_tilt=4*sit+4*stretch*(1-sit)*math.sin(math.pi*flight)
        if kind in ('pet','emote'):
            # The three-quarter artwork has a broad near sleeve and a partly
            # hidden far sleeve. Both hang from the shoulder, rather than
            # folding toward the waist as the old bowed strip did.
            envelope=ease(age/.48)*(1-ease((age-(PET_DURATION-.65))/.65)) if kind=='pet' else 0.
            sway=math.sin(max(0,age-.4)*math.tau/1.6)*envelope
            for side,rotations in (('near',(-8+1.2*sway,4+1.6*sway)),('far',(7-.6*sway,3-.8*sway))):
                a=(246.,302.) if side=='near' else (328.,303.)
                upper,lower=map(math.radians,rotations)
                b=(a[0]+UPPER_ARM*math.sin(upper),a[1]+UPPER_ARM*math.cos(upper))
                c=(b[0]+FOREARM*math.sin(lower),b[1]+FOREARM*math.cos(lower))
                arms[side]=(a,b,c)
        legs={side:leg_joints((303. if side=='far' else 267.,429.),*angles[side]) for side in angles}
        return dict(arms=arms,legs=legs,body_y=body_y,head_tilt=head_tilt,head_dx=head_dx,
                    head_dy=head_dy,body_angle=body_angle,lift=lift,expression=expression,tilt=tilt,leg_angles=angles,
                    neck=(NECK[0],NECK[1]+body_y))

    def procedural(self,kind,age,size,expression=0):
        conf=self.configuration(kind,age,expression);scale=size/500
        out=Image.new('RGBA',tuple(round(v*scale) for v in CANVAS));r=self.rig
        dy=conf['body_y']
        for side in ('far','near'):
            joints=conf['legs'][side]
            # Keep the shoulder/hip root covered by the cardigan/skirt.
            joints=tuple((x,y+dy) for x,y in joints)
            self.leg_layer(out,side,joints,scale)
            ankle=joints[-1]
            # Shoe follows the shin gently; its sock is supplied by the leg.
            foot_angle=conf['leg_angles'][side][1]*.48
            r.paste_pivot(out,self.shoes[side],(16/52,1/22),(ankle[0]*scale,ankle[1]*scale),foot_angle,(52*scale,22*scale))
        flight_arms=None
        if kind in ('pounce','pet','emote'):
            flight_arms={side:self.arm_layer(side,tuple((x,y+dy) for x,y in conf['arms'][side]),scale,out.size,
                None if kind=='pounce' else (35.5 if side=='near' else 29.5)) for side in ('far','near')}
        # A separate neck spans the moving jaw and the stationary collar.
        # The previous art had two independently outlined neck end caps.
        angle=math.radians(conf['head_tilt']);c,s=math.cos(angle),math.sin(angle)
        top=[]
        for x in (-13.,13.):
            top.append((NECK[0]+c*x+s*(-24),NECK[1]+dy-s*x+c*(-24)))
        polygon=(top[0],top[1],(303,300+dy),(265,300+dy))
        neck=Image.new('RGBA',out.size)
        skin=self.neck_texture.resize((round(54*scale),round(44*scale)),Image.Resampling.BICUBIC)
        neck.alpha_composite(skin,(round(257*scale),round((260+dy)*scale)))
        mask=Image.new('L',(out.width*3,out.height*3));ImageDraw.Draw(mask).polygon([(x*scale*3,y*scale*3) for x,y in polygon],fill=255)
        mask=mask.resize(out.size,Image.Resampling.LANCZOS)
        neck.putalpha(ImageChops.multiply(neck.getchannel('A'),mask))
        edge=Image.new('RGBA',(out.width*3,out.height*3));draw=ImageDraw.Draw(edge)
        for a,b in ((polygon[0],polygon[3]),(polygon[1],polygon[2])):
            draw.line((a[0]*scale*3,a[1]*scale*3,b[0]*scale*3,b[1]*scale*3),fill=(81,57,56,255),width=max(1,round(1.5*scale*3)))
        neck.alpha_composite(edge.resize(out.size,Image.Resampling.LANCZOS))
        out.alpha_composite(neck)
        head=self.heads[conf['expression']]
        # Delayed tail sway does not deform eyes or scalp.
        tail_start=r.head_tail_start;mesh=[]
        cuts=[0,tail_start]+[round(tail_start+(412-tail_start)*n/8) for n in range(1,9)]
        def shift(y):
            depth=max(0,(y-tail_start)/(412-tail_start))
            phase=age*math.tau/1.6 if kind=='pet' else age*3
            return depth**1.5*(3*math.sin(phase-depth)+conf['body_angle']*.07)
        for a,b in zip(cuts,cuts[1:]):
            da,db=shift(a),shift(b)
            mesh.append(((0,a,head.width,b),(-da,a,-db,b,head.width-db,b,head.width-da,a)))
        head=head.transform(head.size,Image.Transform.MESH,mesh,Image.Resampling.BICUBIC)
        head=head.resize(tuple(max(1,round(v*scale)) for v in head.size),Image.Resampling.LANCZOS)
        r.paste_pivot(out,head,self.neck_pivot,tuple(v*scale for v in conf['neck']),conf['head_tilt'],head.size)
        if flight_arms is not None:
            torso=Image.new('RGBA',out.size)
            r.paste_pivot(torso,self.flight_torso if kind=='pounce' else self.rest_torso,(.5,0),(282*scale,(286+dy)*scale),0,(132*scale,163*scale))
            if kind!='pounce':out.alpha_composite(flight_arms['far'])
            out.alpha_composite(torso)
            for side in (('far','near') if kind=='pounce' else ('near',)):out.alpha_composite(flight_arms[side])
            # Only opaque jacket pixels cover the shoulder roots. Cutting a
            # round hole in an arm also erased its visible attachment outside
            # the jacket; this local occlusion keeps both hands in front.
            mask=Image.new('L',out.size)
            for side in ('far','near'):
                shoulder=conf['arms'][side][0]
                x,y=shoulder[0]*scale,(shoulder[1]+dy)*scale;radius=13*scale
                ImageDraw.Draw(mask).ellipse((x-radius,y-radius,x+radius,y+radius),fill=255)
            torso.putalpha(ImageChops.multiply(torso.getchannel('A'),mask.filter(ImageFilter.GaussianBlur(1*scale))))
            out.alpha_composite(torso)
        else:
            arm_layers=[]
            for side in ('far','near'):
                image=r.parts[side+'_arm'];joints=tuple((x,y+dy) for x,y in conf['arms'][side])
                layer=Image.new('RGBA',out.size)
                self.strip(layer,image,joints,(39 if side=='near' else 37)*r.width_factors[id(image)],scale)
                arm_layers.append(layer);out.alpha_composite(layer)
            r.paste_pivot(out,self.torso,(.5,0),(282*scale,(286+dy)*scale),0,(132*scale,163*scale))
            for layer in arm_layers:
                mask=Image.new('L',(1,out.height));mask.putdata([round(255*ease((y/scale-330-dy)/18)) for y in range(out.height)])
                layer.putalpha(ImageChops.multiply(layer.getchannel('A'),mask.resize(out.size)));out.alpha_composite(layer)
        angle=conf['body_angle']
        if abs(angle)>.001:
            pad=round(150*scale)
            rotated=Image.new('RGBA',(out.width+2*pad,out.height+2*pad))
            flat=abs(angle)/87
            position=((282-120*flat)*scale+pad,(429-34*flat-conf['lift'])*scale+pad)
            r.paste_pivot(rotated,out,(282/600,429/560),position,angle,out.size)
            # Work on an oversized layer before the final crop. Rotation can
            # expose corners that the upright canvas never needed to contain.
            bounds=rotated.getchannel('A').point(lambda a:255 if a>30 else 0).getbbox()
            margin=4
            dx=max(pad+margin-bounds[0],min(0,pad+out.width-margin-bounds[2]))
            dy=max(pad+margin-bounds[1],min(0,pad+out.height-margin-bounds[3]))
            out=rotated.transform(out.size,Image.Transform.AFFINE,(1,0,pad-dx,0,1,pad-dy),Image.Resampling.BICUBIC)
        return out

    @lru_cache(maxsize=320)
    def cached_frame(self,key,index,size,mirror):
        entry=self.cache[key];sheet=self.sheet(key);w,h=entry['cell'];cols=entry['columns']
        image=sheet.crop(((index%cols)*w,(index//cols)*h,(index%cols+1)*w,(index//cols+1)*h))
        dims=tuple(round(v*size/500) for v in CANVAS)
        if image.size!=dims:image=image.resize(dims,Image.Resampling.LANCZOS)
        return ImageOps.mirror(image) if mirror else image

    @lru_cache(maxsize=2)
    def sheet(self,key):
        return Image.open(self.directory/self.cache[key]['file']).convert('RGBA')

    def render(self,kind,age,size,expression=0,mirror=False):
        key=f'emote-{expression}' if kind=='emote' else kind
        if self.cache and key in self.cache:
            entry=self.cache[key]
            index=min(entry['count']-1,max(0,round(age*entry['fps'])))
            return self.cached_frame(key,index,size,mirror)
        image=self.procedural(kind,age,size,expression)
        return ImageOps.mirror(image) if mirror else image
