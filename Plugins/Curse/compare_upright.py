"""Render public synthetic fixtures using the actual Curse transform."""
from pathlib import Path
from test_upright import FIXTURES, upright
from test_curse import ns
import sys

def svg_path(nodes):
    on=[i for i,n in enumerate(nodes) if n[2]!='offcurve']; out=[]
    out.append('M%g,%g'%nodes[on[0]][:2])
    for a,b in zip(on,on[1:]+on[:1]):
        between=[];j=(a+1)%len(nodes)
        while j!=b:between.append(j);j=(j+1)%len(nodes)
        if len(between)==2:out.append('C'+ ' '.join('%g,%g'%nodes[i][:2] for i in (*between,b)))
        else:out.append('L%g,%g'%nodes[b][:2])
    return ' '.join(out)+'Z'

parts=['<html><meta charset="utf-8"><title>Curse upright bowls</title><style>body{background:#f5f3ef;color:#222;font:16px system-ui;margin:36px}svg{width:100%;max-width:1100px}text{font:18px system-ui}h1{font-size:26px}</style><h1>Curse · Upright bowls</h1><p>Actual plugin output at +12°. Gray outlines show the upright source. All fixtures are synthetic.</p><svg viewBox="0 0 1100 1800">']
for col,value in enumerate((0,.5,1)):
    parts.append(f'<text x="{170+col*320}" y="30">{int(value*100)}%</text>')
for row,(name,source) in enumerate(FIXTURES.items()):
    y=80+row*330;parts.append(f'<text x="0" y="{y}">{name}</text>')
    for col,value in enumerate((0,.5,1)):
        result=upright(source,value)
        scale=.27 if name=='Multiple' else .44
        parts.append(f'<g transform="translate({100+col*320},{y+260}) scale({scale},-{scale})">')
        parts.append('<path fill="#161616" fill-rule="evenodd" d="'+' '.join(svg_path(c) for c in result)+'"/>')
        parts.append('<path fill="none" stroke="#979797" stroke-width="2" d="'+' '.join(svg_path(c) for c in source)+'"/></g>')
parts.append('</svg></html>')
Path(sys.argv[1]).write_text(''.join(parts))
