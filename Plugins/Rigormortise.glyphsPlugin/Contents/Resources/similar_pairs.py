"""Geometry-based pair teaching. No glyph-name exceptions or external dependencies."""
import math
from functools import lru_cache
from spacing_state import effective_authored


def _flatten(commands):
    edges=[];start=point=None
    def line(a,b):
        if a is not None and a!=b:edges.append((a,b))
    def cubic(a,b,c,d,depth=0):
        # Subdivide until both handles lie within 0.35 units of the chord.
        dx,dy=d[0]-a[0],d[1]-a[1];length=math.hypot(dx,dy)
        error=max(abs(dx*(p[1]-a[1])-dy*(p[0]-a[0]))/max(length,1e-9) for p in (b,c))
        if depth>=12 or (length>0 and error<.35):line(a,d);return
        mid=lambda p,q:((p[0]+q[0])/2,(p[1]+q[1])/2)
        ab,bc,cd=mid(a,b),mid(b,c),mid(c,d);abc,bcd=mid(ab,bc),mid(bc,cd);m=mid(abc,bcd)
        cubic(a,ab,abc,m,depth+1);cubic(m,bcd,cd,d,depth+1)
    for cmd in commands:
        kind=cmd[0]
        if kind==0:start=point=(cmd[1],cmd[2])
        elif kind==1:
            new=(cmd[1],cmd[2]);line(point,new);point=new
        elif kind==2:
            new=(cmd[5],cmd[6]);cubic(point,(cmd[1],cmd[2]),(cmd[3],cmd[4]),new);point=new
        elif kind==3:line(point,start);point=start
    return edges


@lru_cache(maxsize=1024)
def _profile(commands,height):
    edges=_flatten(commands)
    if not edges:return None
    xs=[p[0] for edge in edges for p in edge];lo,hi=min(xs),max(xs)
    left=[];right=[]
    for i in range(96):
        y=(-.4+(i+.5)*2/96)*height
        hits=[a[0]+(y-a[1])*(b[0]-a[0])/(b[1]-a[1]) for a,b in edges if (a[1]<=y<b[1]) or (b[1]<=y<a[1])]
        left.append((min(hits)-lo)/height if hits else None)
        right.append((hi-max(hits))/height if hits else None)
    return dict(left=left,right=right)


def profiles(snap):
    h=max(float(snap['xHeight']),1)
    return {name:_profile(tuple(tuple(c) for c in g['commands']),h) for name,g in snap['glyphs'].items()}


def descriptor(a,b):
    return dict(leftFace=a['right'],rightFace=b['left'])


def _face_error(a,b):
    error=0;count=0
    for x,y in zip(a,b):
        if x is None and y is None:continue
        count+=1
        error+=.45**2 if x is None or y is None else min(abs(x-y),1)**2
    return error,count


def _score(a,b):
    error=a[0]+b[0];count=a[1]+b[1]
    return math.exp(-8*math.sqrt(error/max(count,1))) if count else 0


def similarity(a,b):
    return _score(_face_error(a['leftFace'],b['leftFace']),_face_error(a['rightFace'],b['rightFace']))


def effective_value(a,b,raw,groups):
    value=effective_authored(a,b,raw,{},groups)
    return 0 if value is None else value


def adjustments(snap,state):
    rules=state.get('similarRules',{})
    if not rules:return {}
    profile=profiles(snap);raw=dict(snap['pairs']);raw.update(state['pinnedPairs']);values={}
    h=max(float(snap['xHeight']),1)
    prepared=[]
    for rule in rules.values():
        left={n:_face_error(p['right'],rule['descriptor']['leftFace']) for n,p in profile.items() if p}
        right={n:_face_error(p['left'],rule['descriptor']['rightFace']) for n,p in profile.items() if p}
        prepared.append((rule,left,right))
    for a in sorted(profile):
        if not profile[a]:continue
        for b in sorted(profile):
            if not profile[b]:continue
            key=a+'\t'+b
            if key in state['pinnedPairs'] or effective_authored(a,b,raw,state['managedPairs'],snap['groups']) is not None:continue
            best=None
            for rule,left,right in prepared:
                if rule['source']==[a,b]:continue
                score=_score(left[a],right[b]);threshold=rule['threshold']
                if score<threshold:continue
                influence=((score-threshold)/(1-threshold))**.5
                value=rule['deltaEm']*h*rule['strength']*influence
                # Closest lesson wins; overlapping examples never stack.
                if best is None or score>best[0]:best=(score,value)
            if best is not None and abs(best[1])>=.5:values[key]=best[1]
    return values
