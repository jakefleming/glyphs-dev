# encoding: utf-8
from __future__ import division, print_function, unicode_literals

"""
Make Weight — structure-aware weight change (companion to Make Italic).

A plain offset moves every point the same distance along its normal and
so squares off bowls, clogs counters and blobs joins. This filter keeps the
offset as the physical model (a bigger pen) but resolves it per element:

  Weight    total stroke change in units (+ bolder, - lighter).
  Counters  how much of the weight goes OUTWARD instead of into counters
            (50% = symmetric offset, 100% = counters untouched).
  Rounds    round-tension preservation: after the offset, each arc's handles
            are re-set to keep the ORIGINAL handle/leg tension ratio, so a
            superellipse stays a superellipse instead of turning circular or
            square (0% = plain Tiller-Hanson handles).
  Vertical  weight applied to horizontal-tangent parts as a percentage of
            the vertical parts (contrast control).
  Joins     curve/line junctions are re-intersected (clip) so stems stay
            straight and crotches neither blob nor gap; corners are mitered
            with a limit.

Node count and structure are preserved (interpolation-safe).
"""

import objc
import math
import traceback
from GlyphsApp import Glyphs, GSPath, LINE, CURVE, OFFCURVE
from GlyphsApp.plugins import FilterWithDialog
from AppKit import NSView, NSSlider, NSTextField, NSMakeRect, NSFont
from Foundation import NSMakePoint

MITER_LIMIT = 8.0   # corner extension cap, multiples of the offset
THIN_MAX = 0.47     # thinning: max fraction of the local stroke width one side may move
WELD_EPS = 0.25


def _unit(x, y):
	l = math.hypot(x, y)
	if l < 1e-9:
		return None
	return (x / l, y / l)


def _bez(C, t):
	mt = 1 - t
	return (mt**3 * C[0][0] + 3 * mt * mt * t * C[1][0] + 3 * mt * t * t * C[2][0] + t**3 * C[3][0],
		mt**3 * C[0][1] + 3 * mt * mt * t * C[1][1] + 3 * mt * t * t * C[2][1] + t**3 * C[3][1])


def _rayInt(P, d1, Q, d2):
	den = d1[0] * d2[1] - d1[1] * d2[0]
	if abs(den) < 1e-9:
		return None
	qx, qy = Q[0] - P[0], Q[1] - P[1]
	a = (qx * d2[1] - qy * d2[0]) / den
	b = (qx * d1[1] - qy * d1[0]) / den
	return (P[0] + a * d1[0], P[1] + a * d1[1]), a, b


def _lineInt(P, d1, Q, d2):
	r = _rayInt(P, d1, Q, d2)
	return r[0] if r else None


class MakeWeight(FilterWithDialog):

	# ------------------------------------------------------------ UI

	@objc.python_method
	def settings(self):
		self.menuName = "Make Weight"
		self.actionButtonLabel = "Apply"
		W = 300
		view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, W, 240))
		self._rows = {}

		def label(text, y):
			f = NSTextField.alloc().initWithFrame_(NSMakeRect(14, y, W - 100, 18))
			f.setStringValue_(text)
			f.setBezeled_(False)
			f.setDrawsBackground_(False)
			f.setEditable_(False)
			f.setSelectable_(False)
			f.setFont_(NSFont.systemFontOfSize_(12))
			view.addSubview_(f)

		def row(key, title, y, lo, hi, val, fmt):
			label(title, y + 24)
			s = NSSlider.alloc().initWithFrame_(NSMakeRect(14, y, W - 90, 20))
			s.setMinValue_(lo)
			s.setMaxValue_(hi)
			s.setDoubleValue_(val)
			s.setContinuous_(True)
			s.setTarget_(self)
			s.setAction_("sliderChanged:")
			view.addSubview_(s)
			f = NSTextField.alloc().initWithFrame_(NSMakeRect(W - 14 - 54, y, 54, 21))
			f.setStringValue_(fmt % val)
			f.setAlignment_(1)
			f.setFont_(NSFont.monospacedDigitSystemFontOfSize_weight_(12, 0.0))
			f.setTarget_(self)
			f.setAction_("fieldChanged:")
			view.addSubview_(f)
			self._rows[key] = (s, f, fmt)

		row('weight', "Weight", 196, -200, 200, 0, "%+d")
		row('counters', "Counters (outward share)", 148, 0, 100, 60, "%d%%")
		row('rounds', "Rounds (tension preservation)", 100, 0, 100, 100, "%d%%")
		row('vertical', "Vertical (horizontal parts %)", 52, 0, 200, 100, "%d%%")
		self.dialog = view

	@objc.python_method
	def val(self, key):
		return self._rows[key][0].doubleValue()

	def sliderChanged_(self, sender):
		for key, (s, f, fmt) in self._rows.items():
			f.setStringValue_(fmt % round(s.doubleValue()))
		self.update()

	def fieldChanged_(self, sender):
		raw = sender.stringValue().replace("%", "").replace("+", "").strip()
		try:
			v = float(raw)
		except ValueError:
			self.sliderChanged_(sender)
			return
		for key, (s, f, fmt) in self._rows.items():
			if sender is f:
				s.setDoubleValue_(max(s.minValue(), min(s.maxValue(), v)))
		self.sliderChanged_(sender)

	# ------------------------------------------------------------ core

	@objc.python_method
	def pathSegments(self, path):
		nodes = list(path.nodes)
		onIdx = [i for i, n in enumerate(nodes) if n.type != OFFCURVE]
		if len(onIdx) < 2:
			return None
		segs = []
		cnt = len(nodes)
		for k in range(len(onIdx)):
			a = onIdx[k]
			b = onIdx[(k + 1) % len(onIdx)]
			between = []
			i = (a + 1) % cnt
			while i != b:
				between.append(i)
				i = (i + 1) % cnt
			A, B = nodes[a], nodes[b]
			seg = {'iA': a, 'iB': b, 'A': (A.position.x, A.position.y), 'B': (B.position.x, B.position.y),
				'smoothA': bool(A.smooth), 'c1': None, 'c2': None, 'i1': None, 'i2': None}
			if len(between) == 2:
				seg['i1'], seg['i2'] = between
				seg['c1'] = (nodes[between[0]].position.x, nodes[between[0]].position.y)
				seg['c2'] = (nodes[between[1]].position.x, nodes[between[1]].position.y)
			elif between:
				return None
			segs.append(seg)
		return segs

	@objc.python_method
	def segTangents(self, seg):
		A, B, c1, c2 = seg['A'], seg['B'], seg['c1'], seg['c2']
		if c1 is None:
			t = _unit(B[0] - A[0], B[1] - A[1])
			return t, t
		t0 = _unit(c1[0] - A[0], c1[1] - A[1]) or _unit(c2[0] - A[0], c2[1] - A[1]) or _unit(B[0] - A[0], B[1] - A[1])
		t1 = _unit(B[0] - c2[0], B[1] - c2[1]) or _unit(B[0] - c1[0], B[1] - c1[1]) or _unit(B[0] - A[0], B[1] - A[1])
		return t0, t1

	@objc.python_method
	def weightLayer(self, layer, weight, counters, rounds, vertical):
		if abs(weight) < 0.01:
			return
		paths = [s for s in layer.shapes if isinstance(s, GSPath) and s.closed]
		if not paths:
			return

		def signedArea(path):
			pts = [(n.position.x, n.position.y) for n in path.nodes if n.type != OFFCURVE]
			a = 0.0
			for i in range(len(pts)):
				x1, y1 = pts[i]
				x2, y2 = pts[(i + 1) % len(pts)]
				a += x1 * y2 - x2 * y1
			return a / 2.0
		areas = [signedArea(p) for p in paths]
		ccwOuter = areas[max(range(len(paths)), key=lambda i: abs(areas[i]))] > 0

		def whiteN(t):
			return (t[1], -t[0]) if ccwOuter else (-t[1], t[0])

		vfac = vertical   # scale for the y-component (horizontal parts)
		isCounterPath = [(a > 0) != ccwOuter for a in areas]

		# flatten everything once for the ray casts (which side faces what)
		pieces = []
		allSegs = []
		for pi, path in enumerate(paths):
			segs = self.pathSegments(path)
			allSegs.append(segs)
			if not segs:
				continue
			for seg in segs:
				if seg['c1'] is None:
					pts = [seg['A'], seg['B']]
				else:
					C = (seg['A'], seg['c1'], seg['c2'], seg['B'])
					pts = [_bez(C, j / 12.0) for j in range(13)]
				for a, b in zip(pts, pts[1:]):
					pieces.append((a, b, pi))

		def facingPath(P, nW):
			"""(distance, path index) of the first hit casting from P into the black."""
			d = (-nW[0], -nW[1])
			best = None
			for a, b, pi in pieces:
				ex, ey = b[0] - a[0], b[1] - a[1]
				den = d[0] * ey - d[1] * ex
				if abs(den) < 1e-12:
					continue
				qx, qy = a[0] - P[0], a[1] - P[1]
				sdist = (qx * ey - qy * ex) / den
				u = (qx * d[1] - qy * d[0]) / den
				if sdist <= 0.75 or u < -1e-6 or u > 1 + 1e-6:
					continue
				if best is None or sdist < best[0]:
					best = (sdist, pi)
			return best

		for pi, (path, area) in enumerate(zip(paths, areas)):
			segs = allSegs[pi]
			if not segs:
				continue
			nodes = list(path.nodes)
			isCounter = isCounterPath[pi]

			# per-segment amount: which kind of side is this?
			for seg in segs:
				if isCounter:
					seg['amt'] = weight * (1.0 - counters)      # counter side: shrink share
					continue
				if seg['c1'] is None:
					M = ((seg['A'][0] + seg['B'][0]) / 2.0, (seg['A'][1] + seg['B'][1]) / 2.0)
					tM = _unit(seg['B'][0] - seg['A'][0], seg['B'][1] - seg['A'][1])
				else:
					C = (seg['A'], seg['c1'], seg['c2'], seg['B'])
					M = _bez(C, 0.5)
					mt = 0.5
					tM = _unit(3 * (mt * mt * (C[1][0] - C[0][0]) + 2 * mt * mt * (C[2][0] - C[1][0]) + mt * mt * (C[3][0] - C[2][0])),
						3 * (mt * mt * (C[1][1] - C[0][1]) + 2 * mt * mt * (C[2][1] - C[1][1]) + mt * mt * (C[3][1] - C[2][1])))
				hit = facingPath(M, whiteN(tM)) if tM else None
				hitPi = hit[1] if hit else None
				if hitPi is not None and isCounterPath[hitPi]:
					seg['amt'] = weight * counters       # outer side of a counter-bounded stroke
				else:
					seg['amt'] = weight * 0.5            # both sides outer: symmetric pen
				seg['localW'] = hit[0] if hit else None

			# thinning: a side may never travel more than THIN_MAX of the local
			# stroke width, or the two sides cross and the stroke turns inside out
			if weight < 0:
				for seg in segs:
					lw = seg.get('localW')
					if lw is None and not isCounter:
						continue
					if lw is None:
						# counters: measure from this segment's middle too
						if seg['c1'] is None:
							M = ((seg['A'][0] + seg['B'][0]) / 2.0, (seg['A'][1] + seg['B'][1]) / 2.0)
							tM = _unit(seg['B'][0] - seg['A'][0], seg['B'][1] - seg['A'][1])
						else:
							C = (seg['A'], seg['c1'], seg['c2'], seg['B'])
							M = _bez(C, 0.5)
							tM = _unit(C[3][0] - C[0][0] + C[2][0] - C[1][0], C[3][1] - C[0][1] + C[2][1] - C[1][1])
						hit = facingPath(M, whiteN(tM)) if tM else None
						lw = hit[0] if hit else None
					if lw is not None:
						cap = THIN_MAX * lw
						if abs(seg['amt']) > cap:
							seg['amt'] = -cap

			# per-END amounts: a node takes the more conservative (smaller |amt|)
			# of its two segments so the outline stays continuous across joins
			nsegs_ = len(segs)
			for i, seg in enumerate(segs):
				prevS, nextS = segs[i - 1], segs[(i + 1) % nsegs_]
				def pick(a, b):
					return a if abs(a) <= abs(b) else b
				seg['amtA'] = pick(seg['amt'], prevS['amt'])
				seg['amtB'] = pick(seg['amt'], nextS['amt'])

			def dispFor(t, amt):
				n = whiteN(t)
				return (n[0] * amt, n[1] * amt * vfac)

			# ---- offset every segment independently (Tiller-Hanson for curves)
			for seg in segs:
				t0, t1 = self.segTangents(seg)
				if t0 is None or t1 is None:
					seg['oA'], seg['oB'] = seg['A'], seg['B']
					seg['t0'], seg['t1'] = (1, 0), (1, 0)
					continue
				d0, d1 = dispFor(t0, seg['amtA']), dispFor(t1, seg['amtB'])
				seg['t0'], seg['t1'] = t0, t1
				seg['oA'] = (seg['A'][0] + d0[0], seg['A'][1] + d0[1])
				seg['oB'] = (seg['B'][0] + d1[0], seg['B'][1] + d1[1])
				if seg['c1'] is not None:
					pts = (seg['A'], seg['c1'], seg['c2'], seg['B'])
					eT = [_unit(pts[j + 1][0] - pts[j][0], pts[j + 1][1] - pts[j][1]) for j in range(3)]
					eT[0] = eT[0] or eT[1] or t0
					eT[1] = eT[1] or eT[0]
					eT[2] = eT[2] or eT[1]
					offE = []
					edgeAmt = (seg['amtA'], (seg['amtA'] + seg['amtB']) / 2.0, seg['amtB'])
					for j in range(3):
						dj = dispFor(eT[j], edgeAmt[j])
						offE.append(((pts[j][0] + dj[0], pts[j][1] + dj[1]), (pts[j + 1][0] + dj[0], pts[j + 1][1] + dj[1]), eT[j]))
					c1t, c2t = offE[0][1], offE[2][0]
					h1 = _lineInt(offE[0][0], offE[0][2], offE[1][0], offE[1][2])
					h2 = _lineInt(offE[1][0], offE[1][2], offE[2][0], offE[2][2])
					c1n = h1 if h1 is not None else c1t
					c2n = h2 if h2 is not None else c2t
					lim = 4 * max(abs(seg['amtA']), abs(seg['amtB'])) + 4
					if math.hypot(c1n[0] - c1t[0], c1n[1] - c1t[1]) > lim:
						c1n = c1t
					if math.hypot(c2n[0] - c2t[0], c2n[1] - c2t[1]) > lim:
						c2n = c2t
					seg['oc1'], seg['oc2'] = c1n, c2n
					# original tension ratios (handle / leg to the tangent corner)
					hit = _rayInt(seg['A'], t0, seg['B'], (-t1[0], -t1[1]))
					seg['ratio'] = None
					if hit is not None and hit[1] > 0 and hit[2] > 0:
						la = math.hypot(seg['c1'][0] - seg['A'][0], seg['c1'][1] - seg['A'][1])
						lb = math.hypot(seg['c2'][0] - seg['B'][0], seg['c2'][1] - seg['B'][1])
						seg['ratio'] = (la / hit[1], lb / hit[2])

			# ---- junctions: weld smooth, clip curve/line, miter corners
			nseg = len(segs)
			for i in range(nseg):
				prev, cur = segs[i - 1], segs[i]
				E1, E2 = prev['oB'], cur['oA']
				P = cur['A']
				gap = math.hypot(E1[0] - E2[0], E1[1] - E2[1])
				if cur['smoothA'] or gap < WELD_EPS:
					Wp = ((E1[0] + E2[0]) / 2.0, (E1[1] + E2[1]) / 2.0)
					prev['oB'] = cur['oA'] = Wp
					continue
				hit = _rayInt(E1, prev['t1'], E2, cur['t0'])
				if hit is not None and math.hypot(hit[0][0] - P[0], hit[0][1] - P[1]) <= MITER_LIMIT * max(abs(prev['amt']), abs(cur['amt'])) + 2:
					prev['oB'] = cur['oA'] = hit[0]
					continue
				# miter too long: keep the join at the average (bevel would add nodes)
				Wp = ((E1[0] + E2[0]) / 2.0, (E1[1] + E2[1]) / 2.0)
				prev['oB'] = cur['oA'] = Wp

			# ---- rounds: restore the original tension ratio on the new legs
			for seg in segs:
				if seg['c1'] is None or not seg.get('ratio'):
					continue
				A2, B2 = seg['oA'], seg['oB']
				t0, t1 = seg['t0'], seg['t1']
				hit = _rayInt(A2, t0, B2, (-t1[0], -t1[1]))
				if hit is None or hit[1] <= 0 or hit[2] <= 0:
					continue
				ra, rb = seg['ratio']
				g1 = (A2[0] + t0[0] * ra * hit[1], A2[1] + t0[1] * ra * hit[1])
				g2 = (B2[0] - t1[0] * rb * hit[2], B2[1] - t1[1] * rb * hit[2])
				k = rounds
				c1, c2 = seg['oc1'], seg['oc2']
				seg['oc1'] = (c1[0] + (g1[0] - c1[0]) * k, c1[1] + (g1[1] - c1[1]) * k)
				seg['oc2'] = (c2[0] + (g2[0] - c2[0]) * k, c2[1] + (g2[1] - c2[1]) * k)

			# ---- commit (structure unchanged)
			for seg in segs:
				nodes[seg['iA']].position = NSMakePoint(seg['oA'][0], seg['oA'][1])
				if seg['c1'] is not None:
					nodes[seg['i1']].position = NSMakePoint(seg['oc1'][0], seg['oc1'][1])
					nodes[seg['i2']].position = NSMakePoint(seg['oc2'][0], seg['oc2'][1])

	# ------------------------------------------------------------ filter

	@objc.python_method
	def filter(self, layer, inEditView, customParameters):
		try:
			def P(key, default):
				return float(customParameters[key]) if key in customParameters else default
			w = P('weight', self.val('weight'))
			c = P('counters', self.val('counters')) / 100.0
			r = P('rounds', self.val('rounds')) / 100.0
			v = P('vertical', self.val('vertical')) / 100.0
			self.weightLayer(layer, w, c, r, v)
		except Exception:
			print(traceback.format_exc())

	@objc.python_method
	def generateCustomParameter(self):
		return "%s; weight:%d; counters:%d; rounds:%d; vertical:%d" % (
			self.__class__.__name__, round(self.val('weight')), round(self.val('counters')),
			round(self.val('rounds')), round(self.val('vertical')))

	@objc.python_method
	def __file__(self):
		return __file__
