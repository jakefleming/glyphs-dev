"""Translate Glyphs outlines to the engine's plain data format."""

def group_for(glyph):
    import unicodedata
    script=getattr(glyph, 'script', None)
    category=getattr(glyph, 'category', None)
    subcategory=getattr(glyph, 'subCategory', None)
    value=getattr(glyph, 'unicode', None)
    char=None
    if value:
        try:char=chr(int(value,16))
        except (ValueError,TypeError):pass
    if char is None and len(glyph.name.split('.')[0])==1:
        char=glyph.name.split('.')[0]
    if char:
        uc=unicodedata.category(char)
        if not category:category={'L':'Letter','N':'Number','P':'Punctuation','S':'Symbol','M':'Mark','Z':'Separator'}.get(uc[0],uc)
        if not subcategory:subcategory={'Lu':'Uppercase','Ll':'Lowercase','Lt':'Titlecase','Nd':'Decimal Digit'}.get(uc,uc)
        if not script and uc[0]=='L':script=unicodedata.name(char,'unknown').split()[0].lower()
    if not category:return 'unknown|'+glyph.name.split('.')[0]
    return '|'.join(str(v or '') for v in (script,category,subcategory))


def capture(layer):
    # Components, hints and open paths need their own treatment. Don't flatten them.
    if layer.components or layer.hints:
        return None
    paths=[]
    for path in layer.paths:
        if not path.closed or len(path.nodes)>128:return None
        nodes=[]
        for node in path.nodes:
            kind=str(node.type)
            if kind not in ('line','curve','offcurve'):return None
            x,y=float(node.position.x),float(node.position.y)
            import math
            if not math.isfinite(x) or not math.isfinite(y):return None
            nodes.append({'x':x,'y':y,'type':kind,'smooth':bool(node.smooth)})
        paths.append({'closed':True,'nodes':nodes})
    if not paths or sum(len(p['nodes']) for p in paths)>256:return None
    return {'name':layer.parent.name,'group':group_for(layer.parent),'paths':paths}


def corpus(font, master_id, limit=240):
    groups={}
    for glyph in font.glyphs:
        if not glyph.export:continue
        layer=glyph.layers[master_id]
        if layer is None:continue
        data=capture(layer)
        if data:groups.setdefault(data['group'],[]).append(data)
    # Round-robin groups, sampled across each group's full glyph order.
    total=sum(len(v) for v in groups.values())
    if total<=limit:return [g for v in groups.values() for g in v]
    result=[]
    per_group=max(4,limit//max(1,len(groups)))
    for values in groups.values():
        count=min(len(values),per_group)
        result.extend(values[int(i*len(values)/count)] for i in range(count))
    return result[:limit]
