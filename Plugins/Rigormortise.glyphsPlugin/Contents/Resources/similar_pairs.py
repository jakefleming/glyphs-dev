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
def _profile(commands,height,slant=0):
    edges=_flatten(commands)
    if not edges:return None
    xs=[p[0] for edge in edges for p in edge];lo,hi=min(xs),max(xs)
    left=[];right=[]
    for i in range(96):
        y=(-.4+(i+.5)*2/96)*height
        hits=[a[0]+(y-a[1])*(b[0]-a[0])/(b[1]-a[1]) for a,b in edges if (a[1]<=y<b[1]) or (b[1]<=y<a[1])]
        left.append((min(hits)-lo)/height if hits else None)
        right.append((hi-max(hits))/height if hits else None)
    # Compare italic contours in their upright frame while retaining the old
    # profiles so saved version-one lessons reproduce their original behavior.
    shear=math.tan(math.radians(max(-30,min(30,slant))))
    upright=[((a[0]-a[1]*shear,a[1]),(b[0]-b[1]*shear,b[1])) for a,b in edges]
    ux=[p[0] for edge in upright for p in edge];ulo,uhi=min(ux),max(ux)
    ul=[];ur=[]
    for i in range(96):
        y=(-.4+(i+.5)*2/96)*height
        hits=[a[0]+(y-a[1])*(b[0]-a[0])/(b[1]-a[1]) for a,b in upright if (a[1]<=y<b[1]) or (b[1]<=y<a[1])]
        ul.append((min(hits)-ulo)/height if hits else None)
        ur.append((uhi-max(hits))/height if hits else None)
    # Separate vertical ink bands distinguish detached marks from continuous
    # stems. Counters overlap their outer contour's range and add no bands.
    intervals=sorted((min(a[1],b[1]),max(a[1],b[1])) for a,b in edges)
    bands=0;end=-math.inf
    for low,high in intervals:
        if low>end+height*.02:bands+=1
        end=max(end,high)
    return dict(left=left,right=right,uprightLeft=ul,uprightRight=ur,bands=bands,mask=tuple(v is not None for v in ul))


def profiles(snap):
    h=max(float(snap['xHeight']),1)
    return {name:_profile(tuple(tuple(c) for c in g['commands']),h,float(snap.get('slant',0))) for name,g in snap['glyphs'].items()}


def descriptor(a,b):
    left=a.get('uprightRight',a['right']);right=b.get('uprightLeft',b['left'])
    shared=[x is not None and y is not None for x,y in zip(left,right)]
    reach=[min((x for x,ok in zip(face,shared) if ok),default=0) for face in (left,right)]
    return dict(version=2,reach=reach,leftFace=a['right'],rightFace=b['left'],
                localLeftFace=[x-reach[0] if ok else None for x,ok in zip(left,shared)],
                localRightFace=[x-reach[1] if ok else None for x,ok in zip(right,shared)],
                contextLeftFace=left,contextRightFace=right,
                overlap=any(shared),bands=[a.get('bands',1),b.get('bands',1)])


def _face_error(a,b):
    error=0;count=0
    for x,y in zip(a,b):
        if x is None and y is None:continue
        count+=1
        error+=.45**2 if x is None or y is None else min(abs(x-y),1)**2
    return error,count


def _local_face_error(a,b):
    # Nearby extrema need not fall on the same sampled row. Permit one row of
    # vertical movement, with a distance penalty, in both directions.
    def directed(x,y):
        error=0;count=0
        for i,(u,v) in enumerate(zip(x,y)):
            if u is None and v is None:continue
            count+=1
            if u is None or v is None:error+=.45**2;continue
            error+=min(min(abs(u-y[j]),1)**2+((i-j)*2/96)**2
                       for j in range(max(0,i-1),min(len(y),i+2)) if y[j] is not None)
        return error,count
    ab=directed(a,b);ba=directed(b,a)
    return (ab[0]+ba[0])/2,(ab[1]+ba[1])/2


def _score(a,b):
    error=a[0]+b[0];count=a[1]+b[1]
    return math.exp(-8*math.sqrt(error/max(count,1))) if count else 0


def similarity(a,b):
    if a.get('version')==2 and b.get('version')==2:
        if a['bands']!=b['bands'] or a['overlap']!=b['overlap']:return 0
        prefix='local' if a['overlap'] else 'context'
        compare=_local_face_error if a['overlap'] else _face_error
        shape=_score(compare(a[prefix+'LeftFace'],b[prefix+'LeftFace']),
                     compare(a[prefix+'RightFace'],b[prefix+'RightFace']))
        # Local alignment ignores modest terminal offsets, but a large upper
        # overhang still makes a pair an uncertain transfer candidate.
        reach=max((abs(x-y) for x,y in zip(a['reach'],b['reach'])),default=0)
        return min(shape,math.exp(-8*max(0,reach-.06)))
    return _score(_face_error(a['leftFace'],b['leftFace']),_face_error(a['rightFace'],b['rightFace']))


def parse_exclusions(text, names):
    """Explicit preview exclusions use glyph names; names never affect matching."""
    result=set()
    for item in text.replace(';',',').replace('\n',',').split(','):
        if not item.strip():continue
        pair=item.split()
        if len(pair)!=2 or any(n not in names for n in pair):
            raise ValueError('Skipped pairs need two existing glyph names, separated by commas: i period, j period')
        result.add('\t'.join(pair))
    return sorted(result)


def reviewed_pairs(snap,state):
    """New lessons cannot replace a previous lesson's approved spacing."""
    result=set(adjustments(snap,state))
    for rule in state.get('similarRules',{}).values():
        result.update(rule.get('approvedPairs',[]))
    return result


def _profile_similarity(a,b,lesson,cache):
    if [a['bands'],b['bands']]!=lesson['bands']:return 0
    errors=[];reach_error=0
    for side,p,other in (('Left',a,b),('Right',b,a)):
        key=(side,id(p),other['mask'])
        if key not in cache:
            face=p['uprightRight' if side=='Left' else 'uprightLeft']
            shared=[v is not None and ok for v,ok in zip(face,other['mask'])]
            if any(shared)!=lesson['overlap']:cache[key]=None
            else:
                reach=min((v for v,ok in zip(face,shared) if ok),default=0)
                values=[v-reach if ok else None for v,ok in zip(face,shared)] if any(shared) else face
                compare=_local_face_error if any(shared) else _face_error
                prefix='local' if any(shared) else 'context'
                cache[key]=(compare(values,lesson[prefix+side+'Face']),
                            abs(reach-lesson['reach'][0 if side=='Left' else 1]))
        value=cache[key]
        if value is None:return 0
        errors.append(value[0]);reach_error=max(reach_error,value[1])
    return min(_score(*errors),math.exp(-8*max(0,reach_error-.06)))


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
        approved=set(rule['approvedPairs']) if 'approvedPairs' in rule else None
        prepared.append((rule,left,right,approved,set(rule.get('excludedPairs',[])),{}))
    for a in sorted(profile):
        if not profile[a]:continue
        for b in sorted(profile):
            if not profile[b]:continue
            key=a+'\t'+b
            if key in state['pinnedPairs'] or effective_authored(a,b,raw,state['managedPairs'],snap['groups']) is not None:continue
            best=None
            for rule,left,right,approved,excluded,cache in prepared:
                if key in excluded or (approved is not None and key not in approved):continue
                if rule['source']==[a,b]:continue
                score=(_profile_similarity(profile[a],profile[b],rule['descriptor'],cache)
                       if rule['descriptor'].get('version')==2 else _score(left[a],right[b]))
                threshold=rule['threshold']
                if score<threshold:continue
                influence=((score-threshold)/(1-threshold))**.5
                value=rule['deltaEm']*h*rule['strength']*influence
                # Closest lesson wins; overlapping examples never stack.
                if best is None or score>best[0]:best=(score,value)
            if best is not None and abs(best[1])>=.5:values[key]=best[1]
    return values
