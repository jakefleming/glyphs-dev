import json,subprocess,statistics,time
from pathlib import Path
root=Path(__file__).parent
req=json.load(open(root/'engine-request.json'))
proc=subprocess.Popen([str(root.parent/'GraverSpacing.glyphsPlugin/Contents/Resources/graver-spacing-engine')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
def run(req):
 proc.stdin.write(json.dumps(req)+'\n');proc.stdin.flush();return json.loads(proc.stdout.readline())
r=run(req)
assert 'error' not in r,r
snap=json.load(open(root/'live-snapshot.json'))
# Fit the target to Jake's existing lowercase n/o rhythm, avoiding an unrelated cap preference.
spaces=[]
for n in ['n','o']:
 old=snap['glyphs'][n];new=r['metrics'][n]
 spaces.append(48+(old['left']+old['right']-new['left']-new['right'])/2)
req['space']=round(statistics.median(spaces),1)
r=run(req)
json.dump(req,open(root/'calibrated-request.json','w'));json.dump(r,open(root/'engine-result.json','w'))
print('TARGET',req['space'],'ENGINE_MS',r['elapsedMS'])
for n in ['n','o','H','O','A','V','c','quotesingle','period']:
 print(n, [snap['glyphs'][n][s] for s in ['left','right']],r['metrics'][n])
# Repeated processing is deterministic; only affected pairs returned on an edit.
r2=run(req);assert r['metrics']==r2['metrics'] and r['pairs']==r2['pairs']
req['changed']=['n'];r3=run(req);assert len(r3['pairs'])==2*len(req['glyphs'])-1
assert all('n' in p.split('\t') for p in r3['pairs'])
# A fixed sidebearing must not be cancelled by the pair calculation.
req['changed']=None
item=next(g for g in req['glyphs'] if g['name']=='n');item['left']=r['metrics']['n']['left']+40
r4=run(req);assert r4['metrics']['n']['left']==item['left']
assert abs(r4['pairs']['o\tn']-r['pairs']['o\tn'])<=1
# Italics must remain finite and use the same engine path.
req['slant']=12;r5=run(req);assert 'error' not in r5
proc.terminate()
print('PASS deterministic, incremental pairs, fixed-side precedence, italic input')
