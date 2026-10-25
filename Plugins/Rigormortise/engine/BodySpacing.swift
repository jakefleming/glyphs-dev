import Foundation
import CoreGraphics

/// White-space fitting with separate body rhythm and full-outline clearance.
/// Settings affect metrics and pair positions only; editable curves never change.
enum BodySpacing {
    typealias Profile = OpticalSpacing.Profile
    typealias Metrics = OpticalSpacing.Metrics

    fileprivate struct MeasureKey: Hashable { var path: ObjectIdentifier; var height: Double; var space: Double }
    fileprivate struct Measure {
        var profile: Profile
        var height: Double
        var bands: [Int:(left:Double,right:Double)]
        /// `bands` by row from `origin`, NaN where the body has no row.
        var origin: Int
        var leftDepth: [Double]
        var rightDepth: [Double]
        var left: Double
        var right: Double
    }
    // One entry per glyph per master of the font being laid out. A smaller
    // cache re-measured every profile on nearly every pair of a full font.
    private static let measures = RenderCache<MeasureKey,Measure>(capacity:16384)

    private static func importance(_ y: Double, lower: Double, upper: Double) -> Double {
        let t=max(0,min(1,(y-lower)/max(1,upper-lower)))
        return 0.4+0.6*pow(sin(.pi*t),2)
    }
    fileprivate struct ImportanceKey: Hashable { var lower: Double; var upper: Double }
    fileprivate final class ImportanceRows {
        let origin: Int; let weights: [Double]
        init(lower: Double,upper: Double) {
            let first=Int(((lower-2)/4).rounded(.down))-1,last=Int(((upper-2)/4).rounded(.up))+1
            origin=first
            weights=last >= first && last-first < 1<<16 ? (first...last).map { BodySpacing.importance(Double($0)*4+2,lower:lower,upper:upper) } : []
        }
        func weight(_ row: Int,lower: Double,upper: Double) -> Double {
            let i=row-origin
            return i >= 0 && i < weights.count ? weights[i] : BodySpacing.importance(Double(row)*4+2,lower:lower,upper:upper)
        }
    }
    private static let importanceRows=RenderCache<ImportanceKey,ImportanceRows>(capacity:4096)
    /// Everything a whole-font pair table reads, measured once up front and
    /// then only read. Ten workers asking the shared caches for the same
    /// measures spent the pair stage waiting on each other's locks.
    final class PairContext {
        fileprivate let measures: [MeasureKey:Measure]
        fileprivate let upright: [ObjectIdentifier:Profile]
        /// Private scratch per export worker; profile measurements stay shared.
        fileprivate var importance: [ImportanceKey:ImportanceRows] = [:]
        fileprivate init(measures: [MeasureKey:Measure],upright: [ObjectIdentifier:Profile]) { self.measures = measures; self.upright = upright }
        /// The same immutable measures with private scratch per worker.
        func worker() -> PairContext { PairContext(measures:measures,upright:upright) }
    }
    /// Measures every glyph of every master the way `solve` will ask for it.
    static func context(_ masters: [(glyphs: [(Profile,Metrics)],settings: FontSettings)]) throws -> PairContext {
        var measures: [MeasureKey:Measure] = [:], upright: [ObjectIdentifier:Profile] = [:]
        for master in masters {
            let s = master.settings
            guard s.usesBodySpacing else { continue }
            let entries = try ExportWork.map(master.glyphs) { p,m -> [(Profile,Profile,MeasureKey,Measure)] in
                ([p]+(m.baseProfile.map { [$0] } ?? [])).map { source in
                    let measured = OpticalSpacing.measurement(source,settings:s), bodyHeight = m.bodyHeight ?? height(measured,nil,s)
                    return (source,measured,MeasureKey(path:ObjectIdentifier(measured.path),height:bodyHeight,space:measurementScale(s)),measure(measured,height:bodyHeight,space:measurementScale(s)))
                }
            }
            for (source,measured,key,value) in entries.joined() {
                measures[key] = value
                if measured.path !== source.path { upright[ObjectIdentifier(source.path)] = measured }
            }
        }
        return PairContext(measures:measures,upright:upright)
    }
    /// Shape analysis uses a font-relative length, independent of requested
    /// spacing. Tracking must not change the amount of white credited to a shape.
    private static func measurementScale(_ s: FontSettings) -> Double { max(1,s.xHeight*0.08) }

    private static func height(_ p: Profile,_ character: String?,_ s: FontSettings) -> Double {
        if let c = character,c.first?.isNumber == true || (c == c.uppercased() && c != c.lowercased()) { return s.capHeight }
        if let c = character,c.first?.isLetter == true { return s.xHeight }
        return max(1,min(s.capHeight,p.bounds.maxY))
    }
    /// Preserve the established narrow-channel rhythm for stems, wedges and
    /// deep apertures. If more white lies at the body's ends than its middle,
    /// count that receding white as area too: the pattern of a rounded side.
    /// Both bearings and pairs use the same homogeneous, translation-invariant
    /// measure. Doubling matching sides and the scale doubles their credit.
    /// The blend and transition are engineering heuristics, not book ratios.
    private static func channel(_ samples: [Double],weights: [Double],space: Double) -> Double {
        guard let nearest=samples.min() else { return 0 }
        let scale=max(1,space)
        var sum=0.0,total=0.0,area=0.0,middleArea=0.0
        for (depth,weight) in zip(samples,weights) {
            sum += weight*exp(-(depth-nearest)/scale)
            total += weight; area += depth; middleArea += depth*weight
        }
        let narrow=nearest-scale*log(sum/total)
        let mean=area/Double(samples.count),middle=middleArea/total
        // A continuous gate avoids a classification jump as weight/angle moves.
        // Deep central white (including broad wedges and open counters) retains
        // the old measure. Rounded sides gain a bounded share of their area.
        let rounded=max(0,min(1,(mean-middle)/(scale*0.1)))
        return narrow+rounded*(mean-narrow)*(2.0/3)
    }
    private static func measure(_ p: Profile,height: Double,space: Double) -> Measure {
        measures.value(for:MeasureKey(path:ObjectIdentifier(p.path),height:height,space:space)) {
            let lo = max(0,p.bounds.minY), hi = min(height,p.bounds.maxY)
            let lower = hi > lo ? lo : p.bounds.minY, upper = hi > lo ? hi : p.bounds.maxY
            let rows = p.orderedBands.filter { Double($0.key)*4+2 >= lower && Double($0.key)*4+2 <= upper }
            var left: [Double] = rows.map { max(0,$0.value.left-Double(p.bounds.minX)) }
            var right: [Double] = rows.map { max(0,Double(p.bounds.maxX)-$0.value.right) }
            // Project a 45-degree envelope from both sides of each aperture.
            // Deep, narrow counters belong to the letter; broad diagonal white
            // remains available for its neighbor. Two linear passes replace the
            // old, unrelated sidebearing and pair-specific depth caps.
            if rows.count > 1 {
                for i in 1..<rows.count {
                    let dy = Double(rows[i].key-rows[i-1].key)*4
                    left[i] = min(left[i],left[i-1]+dy);right[i] = min(right[i],right[i-1]+dy)
                }
                for i in stride(from:rows.count-2,through:0,by:-1) {
                    let dy = Double(rows[i+1].key-rows[i].key)*4
                    left[i] = min(left[i],left[i+1]+dy);right[i] = min(right[i],right[i+1]+dy)
                }
            }
            var bands: [Int:(left:Double,right:Double)] = [:]
            var ls: [Double] = [],rs: [Double] = [],weights: [Double] = []
            for i in rows.indices {
                bands[rows[i].key] = (left[i],right[i])
                ls.append(left[i]);rs.append(right[i])
                weights.append(importance(Double(rows[i].key)*4+2,lower:lower,upper:upper))
            }
            let origin = rows.first?.key ?? 0, span = rows.isEmpty ? 0 : rows[rows.count-1].key-origin+1
            var leftDepth = [Double](repeating:.nan,count:span), rightDepth = leftDepth
            for i in rows.indices { leftDepth[rows[i].key-origin] = left[i]; rightDepth[rows[i].key-origin] = right[i] }
            return Measure(profile:p,height:height,bands:bands,origin:origin,leftDepth:leftDepth,rightDepth:rightDepth,
                           left:channel(ls,weights:weights,space:space),right:channel(rs,weights:weights,space:space))
        }
    }
    static func metrics(_ p: Profile,letter: Letter,settings s: FontSettings,character: String?) -> Metrics {
        let measured = OpticalSpacing.measurement(p,settings:s)
        let bodyHeight = letter.heightRole == "X-height" ? s.xHeight : height(measured,letter.designCharacter ?? character,s)
        let body = measure(measured,height:bodyHeight,space:measurementScale(s))
        let origin = tan(max(-30,min(30,s.slant ?? 0)) * .pi/180)*s.xHeight*0.5
        let base = s.opticalSpace
        let autoLeft = base-body.left+p.bounds.minX-measured.bounds.minX-origin
        let autoRight = base-body.right+measured.bounds.maxX-p.bounds.maxX+origin
        let adjustmentScale = letter.sidebearingOverride == nil ? 1 : s.spacingFactor
        let leftAdjustment = (letter.leftSpacingAdjustment ?? 0)*adjustmentScale
        let rightAdjustment = (letter.rightSpacingAdjustment ?? 0)*adjustmentScale
        let fixed = (letter.sidebearingOverride ?? s.sidebearing)*s.spacingFactor
        let auto = s.spacingEnabled && letter.sidebearingOverride == nil
        let left = (auto ? autoLeft : fixed)+leftAdjustment
        let right = (auto ? autoRight : fixed)+rightAdjustment
        let advance = max(1,ceil(p.bounds.width+left.rounded()+right.rounded()))
        let shift = left.rounded()-p.bounds.minX
        return Metrics(left:left.rounded(),right:right.rounded(),advance:advance,
                       leftAdjustment:leftAdjustment,rightAdjustment:rightAdjustment,
                       punctuation:OpticalSpacing.Punctuation(character),frameLeft:measured.bounds.minX+shift,
                       frameRight:advance-measured.bounds.maxX-shift,frameWidth:measured.bounds.width,bodyHeight:bodyHeight,
                       fixedLeftAdjustment:letter.sidebearingOverride != nil ? fixed-autoLeft : 0,
                       fixedRightAdjustment:letter.sidebearingOverride != nil ? fixed-autoRight : 0)
    }

    struct Decision {
        var optical: Double
        var clearance: Double
        func value(amount: Double,protect: Bool) -> Double {
            let preferred = optical*max(0,min(1,amount))
            return (protect ? max(preferred,clearance) : preferred).rounded(.up)
        }
    }
    private struct PairKey: Hashable {
        var a: ObjectIdentifier; var b: ObjectIdentifier
        var metrics: [Double]
        var punctuationA: OpticalSpacing.Punctuation; var punctuationB: OpticalSpacing.Punctuation
        var space: Double; var xHeight: Double; var capHeight: Double; var slant: Double
    }
    private struct CachedPair { var a: Profile; var b: Profile; var decision: Decision }
    private static let pairs = RenderCache<PairKey,CachedPair>(capacity:8192)
    static func minimum(settings s: FontSettings,punctuation: Bool) -> Double {
        // Body rhythm is measured elsewhere. Serifs may enter the surrounding
        // white while a smaller independent margin keeps their tips apart.
        max(8,max(0,s.opticalSpace)*(punctuation ? 1 : 0.25))
    }
    static func decision(_ a: Profile,_ am: Metrics,_ b: Profile,_ bm: Metrics,settings s: FontSettings,context: PairContext? = nil) -> Decision {
        // A whole-font table asks for every pair once: nothing to remember.
        if let context { return solve(a,am,b,bm,settings:s,context:context) }
        let key = PairKey(a:ObjectIdentifier(a.path),b:ObjectIdentifier(b.path),
                          metrics:[am.left,am.advance,am.rightAdjustment,am.fixedRightAdjustment,am.bodyHeight ?? -1,am.frameRight ?? 0,am.frameWidth ?? 0,
                                   bm.left,bm.leftAdjustment,bm.fixedLeftAdjustment,bm.bodyHeight ?? -1,bm.frameLeft ?? 0,bm.frameWidth ?? 0],
                          punctuationA:am.punctuation,punctuationB:bm.punctuation,space:s.opticalSpace,
                          xHeight:s.xHeight,capHeight:s.capHeight,slant:s.slant ?? 0)
        return pairs.value(for:key) { CachedPair(a:a,b:b,decision:solve(a,am,b,bm,settings:s)) }.decision
    }
    static func kern(_ a: Profile,_ am: Metrics,_ b: Profile,_ bm: Metrics,settings s: FontSettings,context: PairContext? = nil) -> Double {
        guard s.kerningEnabled else { return 0 }
        return decision(a,am,b,bm,settings:s,context:context).value(amount:s.kerningAmount ?? 1,protect:s.protectsSpacingCollisions)
    }
    private static func solve(_ a: Profile,_ am: Metrics,_ b: Profile,_ bm: Metrics,settings s: FontSettings,context: PairContext? = nil) -> Decision {
        let existing = am.advance-a.bounds.width-am.left+bm.left
        var nearest: Double?
        a.sharedRows(b) { _,right,left in let gap = a.bounds.maxX-right+left-b.bounds.minX; nearest = min(nearest ?? gap,gap) }
        guard let closest = nearest else { return Decision(optical:0,clearance:0) }
        let punctuation = am.punctuation != .none || bm.punctuation != .none
        var floor = minimum(settings:s,punctuation:punctuation)-closest-existing
        func measured(_ p: Profile) -> Profile {
            // An upright pen measures the profile itself, with no lookup.
            guard let context, !context.upright.isEmpty else { return OpticalSpacing.measurement(p,settings:s) }
            return context.upright[ObjectIdentifier(p.path)] ?? OpticalSpacing.measurement(p,settings:s)
        }
        func body(_ p: Profile,_ height: Double) -> Measure {
            context?.measures[MeasureKey(path:ObjectIdentifier(p.path),height:height,space:measurementScale(s))] ?? measure(p,height:height,space:measurementScale(s))
        }
        let ap = measured(a), bp = measured(b)
        let lower = max(0,max(ap.bounds.minY,bp.bounds.minY))
        let upper = min(min(ap.bounds.maxY,bp.bounds.maxY),min(am.bodyHeight ?? height(ap,nil,s),bm.bodyHeight ?? height(bp,nil,s)))
        let ab = body(ap,am.bodyHeight ?? height(ap,nil,s))
        let bb = body(bp,bm.bodyHeight ?? height(bp,nil,s))
        // Rows both bodies occupy, read in row order from the dense tables.
        var samples: [Double] = [],weights: [Double] = []
        let first = max(ab.origin,bb.origin), last = min(ab.origin+ab.rightDepth.count,bb.origin+bb.leftDepth.count)-1
        if first <= last {
            samples.reserveCapacity(last-first+1);weights.reserveCapacity(last-first+1)
            let limits=ImportanceKey(lower:lower,upper:upper)
            let importance: ImportanceRows
            if let context {
                if let known=context.importance[limits] { importance=known }
                else { importance=ImportanceRows(lower:lower,upper:upper);context.importance[limits]=importance }
            } else { importance=importanceRows.value(for:limits) { ImportanceRows(lower:lower,upper:upper) } }
            for row in first...last {
                let right = ab.rightDepth[row-ab.origin], left = bb.leftDepth[row-bb.origin], y = Double(row)*4+2
                if !right.isNaN, !left.isNaN, y >= lower, y <= upper { samples.append(right+left);weights.append(importance.weight(row,lower:lower,upper:upper)) }
            }
        }
        // Both sidebearing and optical pair measurements use the same upright
        // frame. The actual slanted ink above remains the clearance authority.
        let measuredExisting = am.advance+bm.left-b.bounds.minX-am.left+a.bounds.minX+bp.bounds.minX-ap.bounds.maxX
        let adjustments = am.rightAdjustment+bm.leftAdjustment+am.fixedRightAdjustment+bm.fixedLeftAdjustment
        var optical = 0.0
        if samples.count >= 3 {
            optical = 2*s.opticalSpace-measuredExisting-channel(samples,weights:weights,space:2*measurementScale(s))+adjustments
            if abs(optical) < max(3,max(0,s.opticalSpace)*0.04) { optical = 0 }
        }
        if punctuation {
            let space = max(0,s.opticalSpace)
            optical = max(optical,-space*(am.punctuation == .sentence || bm.punctuation == .sentence ? 0.6 : 1))
            let widths = [(am,a),(bm,b)].compactMap { m,p in m.punctuation == .none ? nil : max(0,m.frameWidth ?? p.bounds.width) }
            let overlap = min(space*0.5,(widths.min() ?? 0)*0.25)
            let frameGap = (am.frameRight ?? (am.advance-a.bounds.width-am.left))+(bm.frameLeft ?? bm.left)
            // This footprint guard belongs to optical fitting even when the
            // optional collision check is off; two pairs must not eat a quote.
            optical = max(optical,-overlap-frameGap+am.rightAdjustment+bm.leftAdjustment)
            floor = max(floor,-overlap-frameGap+am.rightAdjustment+bm.leftAdjustment)
        }
        return Decision(optical:optical,clearance:floor)
    }
}
