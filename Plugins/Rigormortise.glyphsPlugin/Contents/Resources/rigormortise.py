# -*- coding: utf-8 -*-
"""Live Rigormortise spacing adapter. All Glyphs object access stays on the main thread."""
import os, json, hashlib, time, copy, traceback, subprocess, threading, queue
import objc
from Foundation import NSObject, NSTimer, NSMakeRect, NSNotificationCenter
from AppKit import (NSMenu, NSMenuItem, NSEvent, NSWindow, NSPanel, NSApplication, NSTextField, NSButton,
                    NSSlider, NSPopUpButton, NSFont, NSAlert, NSBackingStoreBuffered)
from GlyphsApp import Glyphs, GSInstance, EDIT_MENU, UPDATEINTERFACE, Message
from spacing_state import initial_state, detect_adjustments, update_pair_ownership, effective_authored, remember_baseline, observe_changes, adopt_spacing, remember_observation, compact_snapshot
from undo_state import state_delta, restore_state, pair_delta, metric_delta

KEY = 'com.flemingfoundry.graverSpacing.v1'
PREVIEW_KEY = 'com.flemingfoundry.graverSpacing.preview.v1'
PRESETS = [('Saddleshoe Regular — approved', 'saddleshoe-regular-v3', 86),
           ('Saddleshoe Wide Black — study', 'saddleshoe-black-v3', 58)]
RESOURCE = os.path.dirname(os.path.abspath(__file__))


def current_font():
    # Glyphs.font can retain the Macro Panel's source document even while a
    # different document is visibly frontmost. Resolve the actual document window.
    app=NSApplication.sharedApplication()
    windows=([app.mainWindow()] if app.mainWindow() else [])+list(app.orderedWindows())
    for window in windows:
        try:
            document=window.windowController().document()
            font=document.font
            if font in Glyphs.fonts:return font
        except (AttributeError,TypeError):pass
    return None



MASTER_KEY = 'com.flemingfoundry.graverSpacing.master.v2'


def selected_master(font, master_id=None):
    if master_id is None:
        return font.selectedFontMaster or font.masters[0]
    for master in font.masters:
        if master.id == master_id:return master
    raise ValueError('The target master no longer exists.')


def load_state(font, master_id=None):
    master=selected_master(font,master_id)
    raw=master.userData[MASTER_KEY]
    # Old versions had one font-wide state. Migrate it to the first master only;
    # never carry managed pairs or manual pins into a different master.
    if raw is None and master.id==font.masters[0].id:raw=font.userData[KEY]
    if raw is None:
        index=1 if (float(master.axes[0]) if len(master.axes) else 400)>700 else 0
        state=initial_state(PRESETS[index][2]);state['contourPreset']=PRESETS[index][1]
        return state
    try:
        state=json.loads(str(raw))
        if not isinstance(state,dict):return initial_state()
        defaults=initial_state();defaults.update(state)
        return defaults
    except (ValueError,TypeError):return initial_state()


def store_state(font, state, master_id=None):
    selected_master(font,master_id).userData[MASTER_KEY]=json.dumps(state,sort_keys=True,separators=(',',':'))


def kerning_snapshot(font, master):
    names = {g.id: g.name for g in font.glyphs}
    result = {}
    raw = font.kerning.get(master, {})
    for a,row in raw.items():
        for b,v in row.items():
            result[names.get(a,a)+'\t'+names.get(b,b)] = float(v)
    return result


def outline(layer):
    source = layer.copyDecomposedLayer() if len(layer.components) else layer
    if not len(source.paths) or any(not p.closed for p in source.paths):
        return None
    path = source.bezierPath
    if path is None:
        return None
    x = float(source.bounds.origin.x)
    commands = []
    for i in range(path.elementCount()):
        kind, points = path.elementAtIndex_associatedPoints_(i)
        count = {0:1, 1:1, 2:3, 3:0}.get(int(kind))
        if count is None:
            raise ValueError('Unsupported path element')
        cmd = [int(kind)]
        for p in points[:count]:
            cmd.extend([round(float(p.x)-x, 5), round(float(p.y), 5)])
        commands.append(cmd)
    return commands


def set_metrics(layer, left=None, right=None):
    """Translate without Glyphs' LSB setter, which rounds fractional curves."""
    bounds=layer.bounds
    old_left=float(bounds.origin.x)
    old_right=float(layer.width)-old_left-float(bounds.size.width)
    desired_left=old_left if left is None else float(left)
    desired_right=old_right if right is None else float(right)
    dx=round(desired_left-old_left)
    if abs(dx)>1e-8:
        for path in layer.paths:
            for node in path.nodes:
                point=node.position
                node.setPositionFast_round_((float(point.x)+dx,float(point.y)),False)
            if len(path.nodes):path.elementDidChange_(path.nodes[0])
        for anchor in layer.anchors:
            anchor.position=(float(anchor.position.x)+dx,float(anchor.position.y))
        for guide in layer.guides:
            guide.position=(float(guide.position.x)+dx,float(guide.position.y))
    layer.setNeedUpdateShapes()
    layer.width=round(float(bounds.size.width)+old_left+dx+desired_right)
    layer.setNeedUpdateMetrics()
    layer.updateMetrics()


def snapshot(font, master_id=None):
    master = selected_master(font,master_id)
    entries = {}; groups = {}
    for g in font.glyphs:
        groups[g.name] = (('@MMK_R_'+g.leftKerningGroup) if g.leftKerningGroup else '',
                          ('@MMK_L_'+g.rightKerningGroup) if g.rightKerningGroup else '')
        if not g.export or g.category in ('Mark','Separator') or g.name.startswith('.'):
            continue
        if g.script not in (None, '', 'latin') and g.category == 'Letter':
            continue
        layer = g.layers[master.id]
        if layer is None:
            continue
        commands = outline(layer)
        if not commands:
            continue
        char = chr(int(g.unicode,16)) if g.unicode else None
        if not char:
            base = font.glyphs[g.name.split('.')[0]]
            if base and base.unicode:
                char = chr(int(base.unicode,16))
        shape = hashlib.sha256(json.dumps(commands,separators=(',',':')).encode()).hexdigest()
        linkedWidth = bool(g.widthMetricsKey or layer.widthMetricsKey or len(layer.hints))
        entries[g.name] = dict(name=g.name, character=char, shape=shape, commands=commands,
            left=float(layer.bounds.origin.x), right=float(layer.width-layer.bounds.origin.x-layer.bounds.size.width), width=float(layer.width),
            lockLeft=bool(linkedWidth or g.leftMetricsKey or layer.leftMetricsKey or len(layer.components)),
            lockRight=bool(linkedWidth or g.rightMetricsKey or layer.rightMetricsKey or len(layer.components)))
    return dict(master=master.id, xHeight=float(master.xHeight), capHeight=float(master.capHeight),
                slant=float(master.italicAngle), glyphs=entries, groups=groups,
                pairs=kerning_snapshot(font,master.id))


def fingerprint(snap):
    # Selection/camera changes do not launch the spacing engine.
    data = [snap['master'],snap['xHeight'],snap['capHeight'],snap['slant'],
            [(k,g['shape'],round(g['left'],4),round(g['right'],4),g['lockLeft'],g['lockRight'],g['character'])
             for k,g in sorted(snap['glyphs'].items())],snap['pairs'],snap['groups']]
    return hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()


def request_for(snap, state, changed=None):
    glyphs=[]
    for name,g in snap['glyphs'].items():
        item={k:g[k] for k in ('name','character','shape','commands')}
        o=state['overrides'].get(name,{})
        for side in ('left','right'):
            if g['lock'+side.title()]:
                item[side]=g[side]
            elif o.get(side+'Mode')=='fixed':
                item[side]=o[side]
            elif o.get(side+'Mode')=='delta':
                item[side+'Delta']=o[side]
        glyphs.append(item)
    return dict(glyphs=glyphs,xHeight=snap['xHeight'],capHeight=snap['capHeight'],
                space=state['space'],slant=snap['slant'],protect=state['protect'],changed=changed,contourPreset=state.get('contourPreset'))


class Engine:
    def __init__(self):
        self.requests=queue.Queue(); self.results=queue.Queue(); self.process=None
        self.thread=threading.Thread(target=self.work,daemon=True);self.thread.start()
    def work(self):
        while True:
            token,request=self.requests.get()
            if request is None: return
            try:
                if self.process is None or self.process.poll() is not None:
                    self.process=subprocess.Popen([os.path.join(RESOURCE,'rigormortise-engine')],
                        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1)
                self.process.stdin.write(json.dumps(request,separators=(',',':'))+'\n');self.process.stdin.flush()
                line=self.process.stdout.readline()
                if not line: raise RuntimeError('Spacing engine stopped')
                result=json.loads(line)
                self.results.put((token,result))
            except Exception as e:
                self.results.put((token,{'error':str(e)}))
    def stop(self):
        self.requests.put((None,None))
        if self.process and self.process.poll() is None: self.process.terminate()


class RigormortiseUndoRecordV25(NSObject):
    pass


class RigormortiseControllerV25(NSObject):
    def init(self):
        self=objc.super(RigormortiseControllerV25,self).init()
        if self is None: return None
        self.engine=Engine();self.sessions={};self.pending=None;self.serial=0
        self.changedAt=0;self.dirty=True;self.force=False;self.applying=False
        self.window=None;self.status='Off — enable for this font'
        self.active=True;self.undoCount=0
        self.previewQueue=[];self.comparison=None;self.panelFont=None;self.observedSession=None
        return self

    @objc.python_method
    def start(self):
        self.menu=NSMenuItem.alloc().initWithTitle_action_keyEquivalent_('Rigormortise…','showPanel:','')
        self.menu.setTarget_(self);Glyphs.menu[EDIT_MENU].append(self.menu)
        Glyphs.addCallback(self.changed,UPDATEINTERFACE)
        center=NSNotificationCenter.defaultCenter()
        for name in ('NSUndoManagerWillUndoChangeNotification','NSUndoManagerWillRedoChangeNotification'):
            center.addObserver_selector_name_object_(self,'willUndo:',name,None)
        for name in ('NSUndoManagerDidUndoChangeNotification','NSUndoManagerDidRedoChangeNotification'):
            center.addObserver_selector_name_object_(self,'didUndo:',name,None)
        self.timer=NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(0.25,self,'tick:',None,True)

    @objc.python_method
    def stop(self):
        self.active=False;self.timer.invalidate();self.engine.stop()
        Glyphs.removeCallback(self.changed)
        NSNotificationCenter.defaultCenter().removeObserver_(self)
        NSObject.cancelPreviousPerformRequestsWithTarget_(self)
        try: self.menu.menu().removeItem_(self.menu)
        except Exception: pass
        if self.window: self.window.close()

    @objc.python_method
    def changed(self, notification):
        if not self.applying:
            self.dirty=True;self.changedAt=time.monotonic()

    @objc.python_method
    def session(self,font,master_id=None):
        master=selected_master(font,master_id)
        key=(id(font),master.id)
        if key not in self.sessions:
            self.sessions[key]=dict(font=font,master=master.id,state=load_state(font,master.id),last=None,signature=None,force=False)
        return self.sessions[key]

    @objc.python_method
    def persist(self,session):
        manager=session['font'].parent.undoManager()
        manager.disableUndoRegistration()
        try:store_state(session['font'],session['state'],session['master'])
        finally:manager.enableUndoRegistration()

    @objc.python_method
    def setStatus(self,text):
        self.status=text
        if self.window: self.statusLabel.setStringValue_(text)

    def tick_(self,timer):
        if not self.active or self.applying: return
        target=None
        try:
            if self.pending:
                try: token,result=self.engine.results.get_nowait()
                except queue.Empty:
                    if time.monotonic()-self.pending['started']>15:
                        self.engine.stop();self.engine=Engine();raise RuntimeError('Spacing engine timed out; current spacing retained')
                    return
                pending=self.pending
                if token!=pending['token']: return
                self.pending=None
                font=pending['font']
                if font not in Glyphs.fonts or not any(m.id==pending['master'] for m in font.masters):return
                target=self.session(font,pending['master'])
                if not target['state']['enabled'] or target.get('settlingUndo'):return
                # Discard stale calculations, including edits made while the worker ran.
                live=snapshot(font,pending['master'])
                if NSEvent.pressedMouseButtons() or fingerprint(live)!=pending['signature'] or target['state']!=pending['expectedState']:
                    target['force']=True;self.dirty=True;self.changedAt=time.monotonic();return
                if 'error' in result: raise RuntimeError(result['error'])
                if pending['state'].get('adoptPending'):
                    state=adopt_spacing(pending['state'],live,result['metrics'])
                    self.serial+=1
                    self.pending=dict(pending,token=self.serial,state=state,started=time.monotonic())
                    self.engine.requests.put((self.serial,request_for(live,state)))
                    self.setStatus('Remembering your starting spacing…')
                    return
                self.apply(font,live,result,pending['state'])
                return
            font=current_font()
            if self.previewQueue:
                font=self.previewQueue.pop(0);self.force=True;self.dirty=True;self.changedAt=0
            if not font or font not in Glyphs.fonts: return
            s=self.session(font);target=s
            key=(id(font),s['master'])
            if key!=self.observedSession:
                self.observedSession=key;self.dirty=True;self.refreshPanel()
            if not s['state']['enabled'] or s.get('settlingUndo'): return
            if not self.dirty and not self.force and not s.get('force') and s['last'] is not None: return
            if NSEvent.pressedMouseButtons() or time.monotonic()-self.changedAt<0.45: return
            now=snapshot(font,s['master']);signature=fingerprint(now)
            force=self.force or s.get('force',False)
            self.dirty=False
            if signature==s['signature'] and not force: return
            state=copy.deepcopy(s['state'])
            remember_baseline(state,now)
            observe_changes(state,now)
            changed=None
            if s['last'] and not state.get('adoptPending') and not force and all(now[k]==s['last'][k] for k in ('xHeight','capHeight','slant','groups')):
                changed=[n for n,g in now['glyphs'].items() if g!=s['last']['glyphs'].get(n)]
                # Manual pair edits need no recomputation, but save their ownership.
                if not changed:
                    oldstate=copy.deepcopy(s['state'])
                    remember_observation(state,now)
                    s.update(state=state,last=now,signature=signature);self.persist(s)
                    self.registerChange(font,now,now,oldstate,state)
                    return
            self.force=False;s['force']=False;self.serial+=1
            self.pending=dict(token=self.serial,font=font,master=s['master'],signature=signature,state=state,expectedState=copy.deepcopy(s['state']),started=time.monotonic())
            self.setStatus('Updating spacing…')
            self.engine.requests.put((self.serial,request_for(now,state,changed)))
        except Exception as e:
            traceback.print_exc();self.pending=None
            self.active=False
            if target is not None:
                try:
                    target['state']['enabled']=False;self.persist(target)
                except Exception:traceback.print_exc()
            self.setStatus('Paused: '+str(e))

    @objc.python_method
    def undoManager(self,font):
        layers=font.selectedLayers
        return layers[0].parent.undoManager() if layers else font.parent.undoManager()

    @objc.python_method
    def registerChange(self,font,before,after,oldstate,newstate,manager=None):
        metrics=metric_delta(before['glyphs'],after['glyphs'])
        pairs=pair_delta(before['pairs'],after['pairs'])
        state=state_delta(oldstate,newstate)
        if not (metrics or pairs or state):return
        record=RigormortiseUndoRecordV25.alloc().init()
        record.font=font;record.master=before['master'];record.metrics=metrics;record.pairs=pairs;record.state=state
        record.manager=manager if manager is not None else self.undoManager(font)
        m=record.manager
        # Only close a group opened here. Never close Glyphs' event group.
        ownGroup=not m.isUndoing() and not m.isRedoing()
        if ownGroup:m.beginUndoGrouping()
        try:
            m.registerUndoWithTarget_selector_object_(self,'restore:',record)
            m.setActionName_('Rigormortise')
        finally:
            if ownGroup:m.endUndoGrouping()
        self.undoCount+=1

    @objc.python_method
    def sessionsForManager(self,manager):
        return [s for s in self.sessions.values() if s['last'] is not None and s['font'] in Glyphs.fonts and
                (s['font'].parent.undoManager()==manager or any(g.undoManager()==manager for g in s['font'].glyphs))]

    def willUndo_(self,notification):
        if not self.active or self.applying:return
        for s in self.sessionsForManager(notification.object()):
            s['settlingUndo']=True;s['force']=False;s.pop('beforeSetting',None);s.pop('replaceKerning',None)
            self.pending=None;self.force=False;self.dirty=False

    def didUndo_(self,notification):
        if not self.active or self.applying:return
        if self.sessionsForManager(notification.object()):
            self.performSelector_withObject_afterDelay_('finishUndo:',None,0)

    def finishUndo_(self,unused):
        if not self.active:return
        for s in self.sessions.values():
            if s.get('settlingUndo') and s['font'] in Glyphs.fonts and any(m.id==s['master'] for m in s['font'].masters):
                now=snapshot(s['font'],s['master']);s.update(last=now,signature=fingerprint(now),settlingUndo=False)
                remember_observation(s['state'],now);self.persist(s)
        self.pending=None;self.force=False;self.dirty=False
        self.setStatus('Auto on — follows your next edit' if current_font() and self.session(current_font())['state']['enabled'] else 'Off — current spacing retained')
        self.refreshPanel()

    @objc.python_method
    def withoutNativeUndo(self,font,fn):
        managers=[font.parent.undoManager()]+[g.undoManager() for g in font.glyphs]
        unique={str(m):m for m in managers}.values()
        unique=list(unique)
        for m in unique: m.disableUndoRegistration()
        font.disableUpdateInterface();self.applying=True
        try: fn()
        finally:
            font.enableUpdateInterface()
            for m in reversed(unique):m.enableUndoRegistration()
            self.applying=False

    def restore_(self,record):
        font=record.font
        if font not in Glyphs.fonts or not any(m.id==record.master for m in font.masters):return
        session=self.session(font,record.master);before=snapshot(font,record.master);oldstate=copy.deepcopy(session['state'])
        def restore():
            for name,patch in record.metrics.items():
                live=before['glyphs'].get(name)
                if not live or live['shape']!=patch['shape']:continue
                values={side:old for side,(old,new) in patch['sides'].items()
                        if not live['lock'+side.title()] and abs(live[side]-new)<.01}
                if values:set_metrics(font.glyphs[name].layers[record.master],**values)
                if ('width' in patch and len(values)==len(patch['sides']) and not live['lockLeft'] and not live['lockRight']
                    and abs(live['width']-patch['width'][1])<.01):
                    font.glyphs[name].layers[record.master].width=patch['width'][0]
            for key,(old,new) in record.pairs.items():
                if before['pairs'].get(key)!=new:continue
                a,b=key.split('\t')
                if old is None:font.removeKerningForPair(record.master,a,b)
                else:font.setKerningForPair(record.master,a,b,old)
            session['state']=restore_state(session['state'],record.state)
            self.persist(session)
        self.withoutNativeUndo(font,restore)
        after=snapshot(font,record.master)
        # Register the inverse immediately, while Glyphs is collecting redo.
        self.registerChange(font,before,after,oldstate,session['state'],record.manager)
        session['settlingUndo']=True;session['force']=False;session.pop('beforeSetting',None);session.pop('replaceKerning',None)
        self.pending=None;self.force=False;self.dirty=False
        self.performSelector_withObject_afterDelay_('finishUndo:',None,0)

    @objc.python_method
    def apply(self,font,snap,result,state):
        s=self.session(font,snap['master']);oldstate=copy.deepcopy(s.get('beforeSetting',s['state']))
        s.pop('beforeSetting',None)
        preserve=state.pop('preserveEnrollmentMetrics',False)
        changed=False
        def mutate():
            nonlocal changed
            for name,value in result['metrics'].items():
                if preserve:continue
                g=font.glyphs[name];layer=g.layers[snap['master']];old=snap['glyphs'][name]
                left=None if old['lockLeft'] else value['left']
                right=None if old['lockRight'] else value['right']
                if (left is not None and abs(old['left']-left)>0.51) or (right is not None and abs(old['right']-right)>0.51):
                    set_metrics(layer,left,right);changed=True
            managed=state['managedPairs'];pinned=state['pinnedPairs']
            raw=dict(snap['pairs'])
            # Deleted class/mixed pairs also protect their covered glyph pairs.
            raw.update(pinned)
            if s.pop('replaceKerning',False):
                # Explicit one-shot takeover, in the same undo record as spacing.
                # Existing Rigormortise pins survive, including zero-valued pins.
                for key in raw:
                    if key not in pinned:
                        a,b=key.split('\t');font.removeKerningForPair(snap['master'],a,b)
                for key,value in pinned.items():
                    a,b=key.split('\t');font.setKerningForPair(snap['master'],a,b,value)
                managed.clear();raw=dict(pinned)
            for key,value in result['pairs'].items():
                a,b=key.split('\t')
                if key in pinned:continue
                if effective_authored(a,b,raw,managed,snap['groups']) is not None:continue
                current=raw.get(key)
                if value==0:
                    if key in managed:
                        font.removeKerningForPair(snap['master'],a,b);managed.pop(key);changed=True
                else:
                    if current!=value:font.setKerningForPair(snap['master'],a,b,value);changed=True
                    managed[key]=value
            # Remove managed pairs whose glyphs are no longer eligible.
            for key in list(managed):
                if any(n not in snap['glyphs'] for n in key.split('\t')):
                    a,b=key.split('\t');font.removeKerningForPair(snap['master'],a,b);del managed[key];changed=True
            remember_observation(state,snapshot(font,snap['master']))
            s['state']=state;self.persist(s)
        self.withoutNativeUndo(font,mutate)
        now=snapshot(font,snap['master'])
        self.registerChange(font,snap,now,oldstate,state)
        s.update(last=now,signature=fingerprint(now))
        self.dirty=False
        self.engineMS=result['elapsedMS']
        self.setStatus('%s · %d glyphs · overrides preserved' % ('Contour' if state.get('contourPreset') else 'Stock',len(now['glyphs'])))
        self.refreshPanel()
        Glyphs.redraw()

    @objc.python_method
    def enable(self,font,space=None):
        s=self.session(font)
        if 'beforeSetting' not in s:s['beforeSetting']=copy.deepcopy(s['state'])
        now=snapshot(font,s['master'])
        if not s['state']['enabled']:s['state']['adoptPending']=True
        remember_baseline(s['state'],now);observe_changes(s['state'],now)
        remember_observation(s['state'],now)
        if space is not None:s['state']['space']=max(4,min(200,float(space)))
        self.active=True
        s['state']['enabled']=True;self.persist(s);s['force']=True;self.changedAt=0

    def toggle_(self,sender):
        font=current_font()
        if not font:return
        s=self.session(font)
        if s['state']['enabled']:
            oldstate=copy.deepcopy(s['state']);now=snapshot(font,s['master'])
            observe_changes(s['state'],now);remember_observation(s['state'],now)
            s['state']['enabled']=False;s['force']=False;s.pop('replaceKerning',None);s.pop('beforeSetting',None)
            self.persist(s);self.registerChange(font,now,now,oldstate,s['state'])
            self.setStatus('Off — current spacing is retained')
        else:
            try:self.enable(font)
            except Exception as e:Message('Rigormortise',str(e))
        self.refreshPanel()

    def gap_(self,sender):
        font=current_font()
        if not font:return
        s=self.session(font)
        if 'beforeSetting' not in s:s['beforeSetting']=copy.deepcopy(s['state'])
        s['state']['space']=round(sender.doubleValue(),1);self.persist(s)
        s['force']=True;self.changedAt=time.monotonic();self.gapLabel.setStringValue_('Target space: %.1f'%s['state']['space'])

    def protect_(self,sender):
        if not current_font():return
        s=self.session(current_font())
        if 'beforeSetting' not in s:s['beforeSetting']=copy.deepcopy(s['state'])
        s['state']['protect']=bool(sender.state());self.persist(s);s['force']=True

    def pin_(self,sender):
        self.overrideSelected(True)
    def reset_(self,sender):
        self.overrideSelected(False)
    @objc.python_method
    def overrideSelected(self,pin):
        font=current_font()
        if not font:return
        s=self.session(font)
        if 'beforeSetting' not in s:s['beforeSetting']=copy.deepcopy(s['state'])
        for layer in font.selectedLayers:
            if layer.layerId!=s['master']:continue
            if pin:s['state']['overrides'][layer.parent.name]={'leftMode':'fixed','left':float(layer.LSB),'rightMode':'fixed','right':float(layer.RSB)}
            else:s['state']['overrides'].pop(layer.parent.name,None)
        self.persist(s);s['force']=True;self.changedAt=0
        self.setStatus('Selected sidebearings pinned' if pin else 'Selected sidebearings returned to Auto')

    @objc.python_method
    def makePreview(self,source,presetIndex):
        """Create isolated copies; never enroll the source in automatic spacing."""
        if source is None:raise ValueError('Open the source font first.')
        master=source.selectedFontMaster or source.masters[0]
        label,preset,space=PRESETS[presetIndex]
        sourceSession=self.session(source)
        sourceState=copy.deepcopy(sourceSession['state'])
        if sourceSession['last'] is not None:
            live=snapshot(source)
            observe_changes(sourceState,live)
        copies=[]
        for mode in ('Stock','Contour'):
            font=source.copy()
            for m in list(font.masters):
                if m.id!=master.id:font.masters.remove(m)
            # Comparison copies discard extension metadata to avoid competing automation.
            objects=[font]+list(font.masters)+list(font.instances)
            for glyph in font.glyphs:objects.extend([glyph]+list(glyph.layers))
            for obj in objects:
                for key in list(obj.userData.keys() or []):
                    del obj.userData[key]
            font.familyName=source.familyName+' '+master.name+' Rigormortise '+mode
            font.instances=[]
            instance=GSInstance();instance.name=master.name;instance.axes=list(master.axes)
            font.instances.append(instance)
            font.kerning={}
            state=initial_state(space)
            state.update(enabled=True,contourPreset=preset if mode=='Contour' else None,
                         overrides=copy.deepcopy(sourceState['overrides']),
                         pinnedPairs=copy.deepcopy(sourceState['pinnedPairs']))
            # Pins explicitly made in Rigormortise survive; unpinned reference kerning
            # is what the comparison replaces, solely in these new documents.
            for key,value in state['pinnedPairs'].items():
                a,b=key.split('\t')
                if (a.startswith('@') or font.glyphs[a]) and (b.startswith('@') or font.glyphs[b]):
                    font.setKerningForPair(master.id,a,b,value)
            state['baseline']=compact_snapshot(snapshot(font,master.id))
            store_state(font,state)
            font.userData[PREVIEW_KEY]=json.dumps(dict(source=str(source.filepath or source.familyName),
                master=master.id,preset=preset,mode=mode))
            Glyphs.fonts.append(font)
            font.masterIndex=0
            tab=font.newTab('Saddleshoe  Regularity\nry rf very airy raft\nminimum wave KAYAK\n“yes” ‘no’ wait... Why?')
            tab.scale=0.035
            tab.textCursor=0
            self.sessions[(id(font),master.id)]=dict(font=font,master=master.id,state=state,last=None,signature=None,force=True)
            copies.append(font)
        self.comparison=dict(source=source,stock=copies[0],contour=copies[1])
        self.previewQueue.extend(copies)
        self.active=True;self.dirty=True;self.changedAt=0
        self.refreshPanel()
        if self.window:self.window.orderFront_(None)
        self.setStatus('Preparing Stock and Contour copies…')
        return copies

    def preview_(self,sender):
        try:self.makePreview(current_font(),int(self.presetPopup.indexOfSelectedItem()))
        except Exception as e:
            traceback.print_exc();Message('Rigormortise preview',str(e))

    @objc.python_method
    def showComparison(self,which):
        if self.comparison and self.comparison[which] in Glyphs.fonts:
            self.comparison[which].show();self.refreshPanel()
            if self.window:self.window.orderFront_(None)
        else:self.setStatus('Create a comparison first; source remains unchanged.')
    def showStock_(self,sender):self.showComparison('stock')
    def showContour_(self,sender):self.showComparison('contour')
    def showSource_(self,sender):self.showComparison('source')

    def contour_(self,sender):
        font=current_font()
        if not font:return
        s=self.session(font)
        if 'beforeSetting' not in s:s['beforeSetting']=copy.deepcopy(s['state'])
        s['state']['contourPreset']=PRESETS[int(self.presetPopup.indexOfSelectedItem())][1] if sender.state() else None
        self.persist(s);s['force']=True;self.changedAt=0

    def preset_(self,sender):
        font=current_font()
        if not font:return
        s=self.session(font)
        if 'beforeSetting' not in s:s['beforeSetting']=copy.deepcopy(s['state'])
        _,preset,space=PRESETS[int(sender.indexOfSelectedItem())]
        s['state'].update(contourPreset=preset,space=space)
        self.persist(s);s['force']=True;self.changedAt=0;self.refreshPanel()

    def rebuild_(self,sender):
        font=current_font()
        if not font:return
        s=self.session(font)
        # Capture any manual changes before replacing generated kerning.
        now=snapshot(font,s['master'])
        if 'beforeSetting' not in s:s['beforeSetting']=copy.deepcopy(s['state'])
        remember_baseline(s['state'],now);observe_changes(s['state'],now)
        remember_observation(s['state'],now)
        s['last']=now
        s['replaceKerning']=True
        self.pending=None
        self.enable(font);self.refreshPanel()
        self.setStatus('Rebuilding this master; Rigormortise pins will stay. Undo available.')

    def restoreBaseline_(self,sender):
        font=current_font()
        if not font:return
        s=self.session(font);baseline=s['state'].get('baseline')
        if not baseline:
            self.setStatus('No starting baseline saved yet. Enable Auto to capture it.')
            return
        before=snapshot(font,s['master']);oldstate=copy.deepcopy(s['state'])
        self.pending=None;s['force']=False;s.pop('beforeSetting',None);s.pop('replaceKerning',None)
        def restore():
            for name,value in baseline['glyphs'].items():
                live=before['glyphs'].get(name)
                if live is None:continue
                left=None if live['lockLeft'] else value['left']
                right=None if live['lockRight'] else value['right']
                set_metrics(font.glyphs[name].layers[s['master']],left,right)
                if live['shape']==value['shape'] and not live['lockLeft'] and not live['lockRight']:
                    font.glyphs[name].layers[s['master']].width=value['width']
            for key in before['pairs']:
                a,b=key.split('\t');font.removeKerningForPair(s['master'],a,b)
            for key,value in baseline['pairs'].items():
                a,b=key.split('\t')
                if (a.startswith('@') or font.glyphs[a]) and (b.startswith('@') or font.glyphs[b]):
                    font.setKerningForPair(s['master'],a,b,value)
            s['state'].update(enabled=False,overrides={},managedPairs={},pinnedPairs={},adoptPending=True)
            remember_observation(s['state'],snapshot(font,s['master']));self.persist(s)
        self.withoutNativeUndo(font,restore)
        after=snapshot(font,s['master'])
        self.registerChange(font,before,after,oldstate,s['state'])
        s.update(last=after,signature=fingerprint(after))
        self.dirty=False;self.force=False
        self.refreshPanel();self.setStatus('Starting spacing + kerning restored. Auto is off.');Glyphs.redraw()

    @objc.python_method
    def refreshPanel(self):
        if not self.window or not current_font():return
        font=current_font();master=selected_master(font);s=self.session(font)['state']
        self.toggleButton.setState_(int(s['enabled']))
        self.slider.setDoubleValue_(s['space']);self.gapLabel.setStringValue_('Target space: %.1f'%s['space'])
        self.protectButton.setState_(int(s['protect']))
        self.contourButton.setState_(bool(s.get('contourPreset')))
        self.fontLabel.setStringValue_(font.familyName+' / '+master.name)
        index=next((i for i,p in enumerate(PRESETS) if p[1]==s.get('contourPreset')),1 if (float(master.axes[0]) if len(master.axes) else 400)>700 else 0)
        self.presetPopup.selectItemAtIndex_(index)
        key=(id(font),master.id)
        if self.panelFont!=key:
            self.panelFont=key
            if self.active:self.setStatus(('Contour' if s.get('contourPreset') else 'Stock')+' — automatic spacing on' if s['enabled'] else 'Off — current spacing retained')

    def showPanel_(self,sender):
        if not self.window:
            self.window=NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(NSMakeRect(0,0,460,585),3,NSBackingStoreBuffered,False)
            self.window.setTitle_('Rigormortise');self.window.setReleasedWhenClosed_(False);self.window.center()
            self.window.setFloatingPanel_(True);self.window.setLevel_(3)
            view=self.window.contentView()
            def label(text,x,y,w,h):
                item=NSTextField.alloc().initWithFrame_(NSMakeRect(x,y,w,h));item.setStringValue_(text)
                item.setBezeled_(False);item.setDrawsBackground_(False);item.setEditable_(False);item.setSelectable_(False)
                view.addSubview_(item);return item
            def button(text,action,x,y,w,check=False):
                item=NSButton.alloc().initWithFrame_(NSMakeRect(x,y,w,26));item.setTitle_(text);item.setTarget_(self);item.setAction_(action)
                if check:item.setButtonType_(3)
                else:item.setBezelStyle_(1)
                view.addSubview_(item);return item
            self.fontLabel=label('',20,500,420,22)
            self.toggleButton=button('Automatic spacing on this master','toggle:',18,470,420,True)
            self.contourButton=button('Use Contour spacing','contour:',18,443,420,True)
            self.presetPopup=NSPopUpButton.alloc().initWithFrame_pullsDown_(NSMakeRect(20,411,420,26),False)
            self.presetPopup.addItemsWithTitles_([p[0] for p in PRESETS]);self.presetPopup.setTarget_(self);self.presetPopup.setAction_('preset:');view.addSubview_(self.presetPopup)
            self.gapLabel=label('Target space',20,380,420,22)
            self.slider=NSSlider.alloc().initWithFrame_(NSMakeRect(20,353,420,24));self.slider.setMinValue_(4);self.slider.setMaxValue_(160)
            self.slider.setTarget_(self);self.slider.setAction_('gap:');self.slider.setContinuous_(False);view.addSubview_(self.slider)
            self.protectButton=button('Prevent collisions','protect:',18,323,420,True)
            button('Pin selected spacing','pin:',16,291,210);button('Return selected to Auto','reset:',230,291,214)
            label('Manual spacing edits and kerning changes become overrides.',20,268,420,20).setFont_(NSFont.systemFontOfSize_(11))
            button('Replace existing kerning on this master','rebuild:',16,232,428)
            label('Recalculates existing pairs. Keeps Rigormortise pins. Can be undone.',20,209,420,20).setFont_(NSFont.systemFontOfSize_(11))
            label('Enabling Auto alone preserves existing authored kerning.',20,189,420,20).setFont_(NSFont.systemFontOfSize_(11))
            label('Optional comparison in separate files:',20,152,420,22)
            button('Create Stock + Contour preview','preview:',16,119,428)
            label('Uses this master and the selected calibration above.',20,96,420,20).setFont_(NSFont.systemFontOfSize_(11))
            button('View Stock','showStock:',16,58,138);button('View Contour','showContour:',158,58,142);button('Back to source','showSource:',304,58,140)
            self.statusLabel=label(self.status,20,9,420,38);self.statusLabel.setFont_(NSFont.systemFontOfSize_(11))
            for item in list(view.subviews()):
                frame=item.frame();frame.origin.y+=50;item.setFrame_(frame)
            button('Restore starting spacing + kerning','restoreBaseline:',16,9,428)
        self.refreshPanel();self.window.makeKeyAndOrderFront_(None)

RigormortiseController = RigormortiseControllerV25
