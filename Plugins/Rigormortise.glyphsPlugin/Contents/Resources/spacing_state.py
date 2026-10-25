"""Pure ownership rules, independent of Glyphs and its undo system."""
import copy

def pair_key(left, right):
    return left + '\t' + right

def detect_adjustments(state, before, after):
    """Only a metrics-only edit is interpreted as a deliberate spacing change."""
    overrides = state.setdefault('overrides', {})
    for name, current in after.items():
        old = before.get(name)
        if not old:
            continue
        if old['shape'] != current['shape']:
            continue
        for side in ('left', 'right'):
            delta = current[side] - old[side]
            if abs(delta) > 0.51:
                item = overrides.setdefault(name, {})
                if item.get(side + 'Mode') == 'fixed':
                    item[side] = current[side]
                else:
                    item[side + 'Mode'] = 'delta'
                    item[side] = item.get(side, 0) + delta
    return state

def effective_authored(left, right, raw, managed, groups):
    """Glyph-pair, mixed and group values all belong to the author unless owned."""
    lk = groups.get(left, ('', ''))[1]
    rk = groups.get(right, ('', ''))[0]
    for a,b in ((left,right),(left,rk),(lk,right),(lk,rk)):
        if not a or not b:
            continue
        key = pair_key(a,b)
        if key in raw and key not in managed:
            return raw[key]
    return None

def update_pair_ownership(state, current):
    managed = state.setdefault('managedPairs', {})
    pinned = state.setdefault('pinnedPairs', {})
    for key, expected in list(managed.items()):
        actual = current.get(key)
        if actual != expected:
            # Deleting an auto pair is an intentional zero, not permission to recreate it.
            pinned[key] = 0 if actual is None else actual
            del managed[key]


def initial_state(space=48):
    return dict(version=1, enabled=False, space=space, protect=True,
                overrides={}, managedPairs={}, pinnedPairs={})
