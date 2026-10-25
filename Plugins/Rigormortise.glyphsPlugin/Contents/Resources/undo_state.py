"""Conditional, field-level undo patches. Never roll back unrelated later edits."""
import copy
MISSING = {'__graver_absent__': True}

def flatten(state):
    result={}
    for key,value in state.items():
        if key in ('overrides','managedPairs','pinnedPairs'):
            for name,item in value.items():
                result[(key,name)]=copy.deepcopy(item)
        else:result[(key,)]=copy.deepcopy(value)
    return result

def state_delta(before,after):
    a,b=flatten(before),flatten(after)
    return {key:(a.get(key,MISSING),b.get(key,MISSING)) for key in a.keys()|b.keys() if a.get(key,MISSING)!=b.get(key,MISSING)}

def restore_state(current,delta):
    result=copy.deepcopy(current);flat=flatten(current)
    for path,(before,after) in delta.items():
        if flat.get(path,MISSING)!=after:continue
        parent=result
        for k in path[:-1]:parent=parent.setdefault(k,{})
        if before==MISSING:parent.pop(path[-1],None)
        else:parent[path[-1]]=copy.deepcopy(before)
    result['overrides']={n:v for n,v in result.get('overrides',{}).items() if v}
    return result

def pair_delta(before,after):
    return {k:(before.get(k),after.get(k)) for k in before.keys()|after.keys() if before.get(k)!=after.get(k)}

def metric_delta(before,after):
    result={}
    for name,a in before.items():
        b=after.get(name)
        if not b or a['shape']!=b['shape']:continue
        sides={side:(a[side],b[side]) for side in ('left','right') if abs(a[side]-b[side])>.001}
        if sides:
            result[name]={'shape':a['shape'],'sides':sides}
            if 'width' in a and 'width' in b and a['width']!=b['width']:
                result[name]['width']=(a['width'],b['width'])
    return result
