"""Render the actual spacing pass on public synthetic fixtures."""
from pathlib import Path
import math, sys
from test_spacing import run
from test_upright import FIXTURES
from test_curse import output


def svg_path(nodes):
    on=[i for i,n in enumerate(nodes) if n[2]!='offcurve']
    result=['M%g,%g'%nodes[on[0]][:2]]
    for a,b in zip(on,on[1:]+on[:1]):
        ids=[];i=(a+1)%len(nodes)
        while i!=b:ids.append(i);i=(i+1)%len(nodes)
        if len(ids)==2:result.append('C'+' '.join('%g,%g'%nodes[j][:2] for j in (*ids,b)))
        else:result.append('L%g,%g'%nodes[b][:2])
    return ' '.join(result)+'Z'


def render():
    body=[];k=math.tan(math.radians(24))
    for row,(name,source) in enumerate(FIXTURES.items()):
        y=70+row*310
        height=max(n[1] for p in source for n in p)
        body.append(f'<text x="20" y="{y}">{name}</text>')
        for col,amount in enumerate((0,.5,1)):
            layer=run(source,amount,24.,upright=1.)
            left=70+col*400
            body.append(f'<text x="{left}" y="{y+30}">{amount*100:g}% · advance {layer.width:.2f}</text>')
            scale=.22 if name=='Multiple' else .35
            body.append(f'<g transform="translate({left+55},{y+250}) scale({scale},-{scale})">')
            for origin in (0,layer.width):
                body.append(f'<path d="M{origin-250*k},0 L{origin+(height-250)*k},{height}" stroke="#598caa" stroke-width="3" stroke-dasharray="10 8"/>')
            body.append('<path fill="#232323" fill-rule="evenodd" d="'+' '.join(svg_path(p) for p in output(layer))+'"/></g>')
    svg='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 1630" style="font:17px system-ui">'+''.join(body)+'</svg>'
    return '<html><meta charset="utf-8"><title>Curse spacing</title><style>body{background:#f5f3ef;color:#222;font:16px system-ui;margin:32px}svg{width:100%;max-width:1280px}</style><h1>Curse · Spacing</h1><p>Actual plugin output at +24°, Stem weight 100%, Upright bowls 100%. Blue lines show slanted advance boundaries. All fixtures are synthetic.</p>'+svg+'</html>'

if __name__=='__main__':Path(sys.argv[1]).write_text(render())
