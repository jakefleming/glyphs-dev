import Foundation
import CoreGraphics

/// Deterministic outline-band spacing. Values are in font units; sketches are never modified.
enum OpticalSpacing {
    // Retain the path with its identity-keyed profile so an address cannot be reused.
    private static let profiles = RenderCache<ObjectIdentifier, (CGPath, Profile)>()
    static func profile(_ path: CGPath) -> Profile {
        profiles.value(for:ObjectIdentifier(path)) { (path,Profile(path)) }.1
    }
    struct Profile {
        let path: CGPath
        let bounds: CGRect
        var bands: [Int: (left: Double, right: Double)] = [:]
        var orderedBands: [(key:Int,value:(left:Double,right:Double))] = []
        /// The same rows as `bands`, contiguous from `rowOrigin`, with NaN in
        /// rows that hold no ink. A font's pair scan reads two profiles row
        /// against row millions of times; this avoids hashing every row.
        private(set) var rowOrigin = 0
        private(set) var denseLeft: [Double] = []
        private(set) var denseRight: [Double] = []
        /// Every row both profiles occupy, in ascending order: this profile's
        /// right edge and the other's left edge.
        @inline(__always) func sharedRows(_ other: Profile,_ body: (_ row: Int,_ right: Double,_ left: Double) -> Void) {
            guard !denseRight.isEmpty, !other.denseLeft.isEmpty else {
                for row in orderedBands { if let next = other.bands[row.key] { body(row.key,row.value.right,next.left) } }
                return
            }
            let lo = max(rowOrigin,other.rowOrigin), hi = min(rowOrigin+denseRight.count,other.rowOrigin+other.denseLeft.count)-1
            guard lo <= hi else { return }
            for row in lo...hi {
                let right = denseRight[row-rowOrigin], left = other.denseLeft[row-other.rowOrigin]
                if !right.isNaN, !left.isNaN { body(row,right,left) }
            }
        }
        init(_ path: CGPath) {
            self.path = path
            // Soft ink can erase a complete glyph. CGRect.null carries
            // infinite origins, which would poison bearings and placement.
            bounds = path.isEmpty ? .zero : path.boundingBoxOfPath
            var current = CGPoint.zero, start = CGPoint.zero
            func edge(_ a: CGPoint, _ b: CGPoint) {
                let lo = Int(floor(min(a.y,b.y)/4)), hi = Int(floor(max(a.y,b.y)/4))
                for row in lo...hi {
                    let y0 = max(min(a.y,b.y), Double(row)*4), y1 = min(max(a.y,b.y),Double(row+1)*4)
                    func x(_ y: Double) -> Double { abs(b.y-a.y) < 0.00001 ? a.x : a.x+(b.x-a.x)*(y-a.y)/(b.y-a.y) }
                    let left = abs(b.y-a.y) < 0.00001 ? min(a.x,b.x) : min(x(y0),x(y1))
                    let right = abs(b.y-a.y) < 0.00001 ? max(a.x,b.x) : max(x(y0),x(y1))
                    let old = bands[row] ?? (left,right)
                    bands[row] = (min(old.left,left),max(old.right,right))
                }
            }
            path.applyWithBlock { pointer in
                let e = pointer.pointee
                switch e.type {
                case .moveToPoint: current = e.points[0]; start = current
                case .addLineToPoint: edge(current,e.points[0]); current = e.points[0]
                case .addCurveToPoint, .addQuadCurveToPoint:
                    let origin = current
                    let quad = e.type == .addQuadCurveToPoint
                    let end = e.points[quad ? 1 : 2]
                    var c1 = e.points[0], c2 = e.points[1]
                    if quad {
                        c1 = CurveFit.add(origin,CurveFit.mul(CurveFit.sub(e.points[0],origin),2.0/3))
                        c2 = CurveFit.add(end,CurveFit.mul(CurveFit.sub(e.points[0],end),2.0/3))
                    }
                    // Construction cells encode straight edges as cubics to
                    // retain master grammar. Measure those edges once, rather
                    // than subdividing every straight edge into 48 pieces.
                    let delta=CurveFit.sub(end,origin)
                    let d1=CurveFit.sub(c1,CurveFit.add(origin,CurveFit.mul(delta,1.0/3)))
                    let d2=CurveFit.sub(c2,CurveFit.add(origin,CurveFit.mul(delta,2.0/3)))
                    if hypot(d1.x,d1.y)<1e-9, hypot(d2.x,d2.y)<1e-9 {
                        edge(origin,end);current=end;return
                    }
                    let curve = CurveFit.Cubic(p0:origin,p1:c1,p2:c2,p3:end)
                    for i in 1...48 { let p = curve.point(Double(i)/48); edge(current,p); current = p }
                case .closeSubpath: edge(current,start); current = start
                @unknown default: break
                }
            }
            orderedBands = bands.sorted { $0.key < $1.key }
            if let first = orderedBands.first?.key, let last = orderedBands.last?.key, last-first < 1<<16 {
                rowOrigin = first
                denseLeft = [Double](repeating:.nan,count:last-first+1); denseRight = denseLeft
                for row in orderedBands { denseLeft[row.key-first] = row.value.left; denseRight[row.key-first] = row.value.right }
            }
        }
    }
    private struct MeasurementKey: Hashable { var path: ObjectIdentifier; var slant: Double }
    private static let measurements = RenderCache<MeasurementKey, (CGPath, Profile)>(capacity:16384)
    static func measurement(_ p: Profile, settings s: FontSettings) -> Profile {
        let slant = max(-30,min(30,s.slant ?? 0))
        guard abs(slant) > 0.00001 else { return p }
        return measurements.value(for:MeasurementKey(path:ObjectIdentifier(p.path),slant:slant)) {
            var undoLean = CGAffineTransform(a:1,b:0,c:-tan(slant * .pi/180),d:1,tx:0,ty:0)
            return (p.path,Profile(p.path.copy(using:&undoLean)!))
        }.1
    }
    enum Punctuation: Hashable {
        case none, sentence, compact, delimiter
        init(_ character: String?) {
            guard let character, character.count == 1 else { self = .none; return }
            if "?!¿¡‽⸘".contains(character) { self = .sentence }
            else if ".,:;…'\"‘’‚‛“”„‟«»‹›".contains(character) { self = .compact }
            else if "()[]{}".contains(character) { self = .delimiter }
            else { self = .none }
        }
    }
    struct Metrics {
        var allowsSwashOverhang = false
        var baseProfile: Profile? = nil
        var accentBounds: [CGRect] = []
        var combining: Bool = false
        var ideographic: Bool = false
        var left: Double; var right: Double; var advance: Double
        var leftAdjustment: Double; var rightAdjustment: Double
        var punctuation: Punctuation = .none
        // Bounding-box bearings in the shared slanted spacing frame. These
        // protect a short mark from being consumed by two independent pairs.
        var frameLeft: Double? = nil; var frameRight: Double? = nil
        var frameWidth: Double? = nil
        /// `Letter.markAnchors`, carried to where marks are placed.
        var markAnchors: [String:Double]? = nil
        var bodyHeight: Double? = nil
        var fixedLeftAdjustment: Double = 0
        var fixedRightAdjustment: Double = 0
    }
}
