# -*- coding: utf-8 -*-
"""Live Graver spacing adapter. All Glyphs object access stays on the main thread."""
import os, json, hashlib, time, copy, traceback, subprocess, threading, queue
import objc
from Foundation import NSObject, NSTimer, NSMakeRect, NSNotificationCenter
from AppKit import (NSMenu, NSMenuItem, NSEvent, NSWindow, NSPanel, NSApplication, NSTextField, NSButton,
                    NSSlider, NSFont, NSAlert, NSBackingStoreBuffered)
from GlyphsApp import Glyphs, EDIT_MENU, UPDATEINTERFACE, Message
from spacing_state import initial_state, detect_adjustments, update_pair_ownership, effective_authored
from undo_state import state_delta, restore_state, pair_delta, metric_delta

KEY = 'com.flemingfoundry.graverSpacing.v1'
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



def load_state(font):
    raw = font.userData[KEY]
    if raw is None:return initial_state()
    try:
        state=json.loads(str(raw))
        if not isinstance(state,dict):return initial_state()
        defaults=initial_state();defaults.update(state)
        return defaults
    except (ValueError,TypeError):
        return initial_state()


def store_state(font, state):
    font.userData[KEY] = json.dumps(state, sort_keys=True, separators=(',', ':'))


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


def snapshot(font):
    if len(font.masters) != 1:
        raise ValueError('This first version supports single-master fonts. Multiple masters are left unchanged.')
    master = font.masters[0]
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
                space=state['space'],slant=snap['slant'],protect=state['protect'],changed=changed)


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
                    self.process=subprocess.Popen([os.path.join(RESOURCE,'graver-spacing-engine')],
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


class GraverSpacingUndoRecordV13(NSObject):
    pass


class GraverSpacingControllerV13(NSObject):
    def init(self):
        self=objc.super(GraverSpacingControllerV13,self).init()
        if self is None: return None
        self.engine=Engine();self.sessions={};self.pending=None;self.serial=0
        self.changedAt=0;self.dirty=True;self.force=False;self.applying=False
        self.window=None;self.status='Off — enable for this font'
        self.active=True;self.undoCount=0
        return self

    @objc.python_method
    def start(self):
        self.menu=NSMenuItem.alloc().initWithTitle_action_keyEquivalent_('Graver Spacing…','showPanel:','')
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
    def session(self,font):
        key=id(font)
        if key not in self.sessions:
            self.sessions[key]=dict(font=font,state=load_state(font),last=None,signature=None)
        return self.sessions[key]

    @objc.python_method
    def persist(self,session):
        manager=session['font'].parent.undoManager()
        manager.disableUndoRegistration()
        try:store_state(session['font'],session['state'])
        finally:manager.enableUndoRegistration()

    @objc.python_method
    def setStatus(self,text):
        self.status=text
        if self.window: self.statusLabel.setStringValue_(text)

    def tick_(self,timer):
        if not self.active or self.applying: return
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
                if font not in Glyphs.fonts or not self.session(font)['state']['enabled']: return
                # Discard stale calculations, including edits made while the worker ran.
                live=snapshot(font)
                if NSEvent.pressedMouseButtons() or fingerprint(live)!=pending['signature'] or self.session(font)['state']!=pending['expectedState']:
                    self.dirty=True;self.force=True;self.changedAt=time.monotonic();return
                if 'error' in result: raise RuntimeError(result['error'])
                self.apply(font,live,result,pending['state'])
                return
            font=current_font()
            if not font: return
            s=self.session(font)
            if not s['state']['enabled'] or s.get('settlingUndo'): return
            if not self.dirty and not self.force and s['last'] is not None: return
            if NSEvent.pressedMouseButtons() or time.monotonic()-self.changedAt<0.45: return
            now=snapshot(font);signature=fingerprint(now)
            self.dirty=False
            if signature==s['signature'] and not self.force: return
            state=copy.deepcopy(s['state'])
            if s['last']:
                detect_adjustments(state,s['last']['glyphs'],now['glyphs'])
            update_pair_ownership(state,now['pairs'])
            changed=None
            if s['last'] and not self.force and all(now[k]==s['last'][k] for k in ('xHeight','capHeight','slant','groups')):
                changed=[n for n,g in now['glyphs'].items() if g!=s['last']['glyphs'].get(n)]
                # Manual pair edits need no recomputation, but save their ownership.
                if not changed:
                    oldstate=copy.deepcopy(s['state'])
                    s.update(state=state,last=now,signature=signature);self.persist(s)
                    self.registerChange(font,now,now,oldstate,state)
                    return
            self.force=False;self.serial+=1
            self.pending=dict(token=self.serial,font=font,signature=signature,state=state,expectedState=copy.deepcopy(s['state']),started=time.monotonic())
            self.setStatus('Updating spacing…')
            self.engine.requests.put((self.serial,request_for(now,state,changed)))
        except Exception as e:
            traceback.print_exc();self.pending=None
            self.active=False
            if current_font():
                try:
                    s=self.session(current_font());s['state']['enabled']=False;self.persist(s)
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
        record=GraverSpacingUndoRecordV13.alloc().init()
        record.font=font;record.master=before['master'];record.metrics=metrics;record.pairs=pairs;record.state=state
        record.manager=manager if manager is not None else self.undoManager(font)
        m=record.manager
        # Only close a group opened here. Never close Glyphs' event group.
        ownGroup=not m.isUndoing() and not m.isRedoing()
        if ownGroup:m.beginUndoGrouping()
        try:
            m.registerUndoWithTarget_selector_object_(self,'restore:',record)
            m.setActionName_('Graver Spacing')
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
            s['settlingUndo']=True
            self.pending=None;self.force=False;self.dirty=False

    def didUndo_(self,notification):
        if not self.active or self.applying:return
        if self.sessionsForManager(notification.object()):
            self.performSelector_withObject_afterDelay_('finishUndo:',None,0)

    def finishUndo_(self,unused):
        if not self.active:return
        for s in self.sessions.values():
            if s.get('settlingUndo') and s['font'] in Glyphs.fonts:
                now=snapshot(s['font']);s.update(last=now,signature=fingerprint(now),settlingUndo=False)
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
        if font not in Glyphs.fonts:return
        session=self.session(font);before=snapshot(font);oldstate=copy.deepcopy(session['state'])
        def restore():
            for name,patch in record.metrics.items():
                live=before['glyphs'].get(name)
                if not live or live['shape']!=patch['shape']:continue
                values={side:old for side,(old,new) in patch['sides'].items()
                        if not live['lock'+side.title()] and abs(live[side]-new)<.01}
                if values:set_metrics(font.glyphs[name].layers[record.master],**values)
            for key,(old,new) in record.pairs.items():
                if before['pairs'].get(key)!=new:continue
                a,b=key.split('\t')
                if old is None:font.removeKerningForPair(record.master,a,b)
                else:font.setKerningForPair(record.master,a,b,old)
            session['state']=restore_state(session['state'],record.state)
            self.persist(session)
        self.withoutNativeUndo(font,restore)
        after=snapshot(font)
        # Register the inverse immediately, while Glyphs is collecting redo.
        self.registerChange(font,before,after,oldstate,session['state'],record.manager)
        session['settlingUndo']=True
        self.pending=None;self.force=False;self.dirty=False
        self.performSelector_withObject_afterDelay_('finishUndo:',None,0)

    @objc.python_method
    def apply(self,font,snap,result,state):
        s=self.session(font);oldstate=copy.deepcopy(s.get('beforeSetting',s['state']))
        s.pop('beforeSetting',None)
        changed=False
        def mutate():
            nonlocal changed
            for name,value in result['metrics'].items():
                g=font.glyphs[name];layer=g.layers[snap['master']];old=snap['glyphs'][name]
                left=None if old['lockLeft'] else value['left']
                right=None if old['lockRight'] else value['right']
                if (left is not None and abs(old['left']-left)>0.51) or (right is not None and abs(old['right']-right)>0.51):
                    set_metrics(layer,left,right);changed=True
            managed=state['managedPairs'];pinned=state['pinnedPairs']
            for key,value in result['pairs'].items():
                a,b=key.split('\t')
                if key in pinned:continue
                if effective_authored(a,b,snap['pairs'],managed,snap['groups']) is not None:continue
                current=snap['pairs'].get(key)
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
            s['state']=state;self.persist(s)
        self.withoutNativeUndo(font,mutate)
        now=snapshot(font)
        self.registerChange(font,snap,now,oldstate,state)
        s.update(last=now,signature=fingerprint(now))
        self.dirty=False
        self.engineMS=result['elapsedMS']
        self.setStatus('Auto on · %d glyphs · your overrides preserved' % len(now['glyphs']))
        Glyphs.redraw()

    @objc.python_method
    def enable(self,font,space=None):
        if len(font.masters)!=1:raise ValueError('Use a single-master font for this first version.')
        s=self.session(font)
        if 'beforeSetting' not in s:s['beforeSetting']=copy.deepcopy(s['state'])
        if space is not None:s['state']['space']=max(4,min(200,float(space)))
        s['state']['enabled']=True;self.persist(s);self.force=True;self.changedAt=0

    def toggle_(self,sender):
        font=current_font()
        if not font:return
        s=self.session(font)
        if s['state']['enabled']:
            s['state']['enabled']=False;self.persist(s);self.setStatus('Off — current spacing is retained')
        else:
            try:self.enable(font)
            except Exception as e:Message('Graver Spacing',str(e))
        self.refreshPanel()

    def gap_(self,sender):
        font=current_font()
        if not font:return
        s=self.session(font)
        if 'beforeSetting' not in s:s['beforeSetting']=copy.deepcopy(s['state'])
        s['state']['space']=round(sender.doubleValue(),1);self.persist(s)
        self.force=True;self.changedAt=time.monotonic();self.gapLabel.setStringValue_('Target space: %.1f'%s['state']['space'])

    def protect_(self,sender):
        if not current_font():return
        s=self.session(current_font())
        if 'beforeSetting' not in s:s['beforeSetting']=copy.deepcopy(s['state'])
        s['state']['protect']=bool(sender.state());self.persist(s);self.force=True

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
            if pin:s['state']['overrides'][layer.parent.name]={'leftMode':'fixed','left':float(layer.LSB),'rightMode':'fixed','right':float(layer.RSB)}
            else:s['state']['overrides'].pop(layer.parent.name,None)
        self.persist(s);self.force=True;self.changedAt=0
        self.setStatus('Selected sidebearings pinned' if pin else 'Selected sidebearings returned to Auto')

    @objc.python_method
    def refreshPanel(self):
        if not self.window or not current_font():return
        s=self.session(current_font())['state'];self.toggleButton.setState_(int(s['enabled']))
        self.slider.setDoubleValue_(s['space']);self.gapLabel.setStringValue_('Target space: %.1f'%s['space'])
        self.protectButton.setState_(int(s['protect']))

    def showPanel_(self,sender):
        if not self.window:
            self.window=NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(NSMakeRect(0,0,390,245),3,NSBackingStoreBuffered,False)
            self.window.setTitle_('Graver Spacing');self.window.setReleasedWhenClosed_(False);self.window.center()
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
            self.toggleButton=button('Automatic spacing for this font','toggle:',18,204,350,True)
            self.gapLabel=label('Target space',20,171,350,22)
            self.slider=NSSlider.alloc().initWithFrame_(NSMakeRect(20,143,350,24));self.slider.setMinValue_(4);self.slider.setMaxValue_(160)
            self.slider.setTarget_(self);self.slider.setAction_('gap:');self.slider.setContinuous_(False);view.addSubview_(self.slider)
            self.protectButton=button('Prevent collisions','protect:',18,108,350,True)
            button('Pin selected spacing','pin:',16,69,180);button('Return selected to Auto','reset:',196,69,180)
            label('Manual spacing edits become persistent adjustments.',20,42,350,20)
            self.statusLabel=label(self.status,20,9,350,28);self.statusLabel.setFont_(NSFont.systemFontOfSize_(11))
        self.refreshPanel();self.window.makeKeyAndOrderFront_(None)

GraverSpacingController = GraverSpacingControllerV13
