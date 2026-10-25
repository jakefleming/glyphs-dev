import Foundation
import CoreGraphics
struct InputGlyph: Decodable {
    var name: String; var character: String?; var shape: String
    var commands: [[Double]]
    var left: Double?; var right: Double?
    var leftDelta: Double?; var rightDelta: Double?
}
struct Request: Decodable {
    var glyphs: [InputGlyph]; var xHeight: Double; var capHeight: Double
    var space: Double; var slant: Double; var protect: Bool
    var changed: [String]?
    var contourPreset: String?
}
struct ResultGlyph: Encodable { var left: Double; var right: Double; var width: Double }
struct Reply: Encodable { var metrics: [String:ResultGlyph]; var pairs: [String:Double]; var elapsedMS: Double }
var cache: [String:OpticalSpacing.Profile] = [:]
func run(_ r: Request) throws -> Reply {
    guard r.glyphs.count <= 2000, r.xHeight > 0, r.capHeight > 0, (0...1000).contains(r.space) else { throw NSError(domain:"Invalid spacing request",code:1) }
    let start=Date()
    var settings=FontSettings(xHeight:r.xHeight,capHeight:r.capHeight,sidebearing:r.space,slant:r.slant)
    settings.protectsSpacingCollisions=r.protect
    var entries: [(InputGlyph,OpticalSpacing.Profile,OpticalSpacing.Metrics)] = []
    var results: [String:ResultGlyph] = [:]
    for g in r.glyphs {
        let p: OpticalSpacing.Profile
        if let known=cache[g.shape] { p=known }
        else {
            let path=CGMutablePath()
            for c in g.commands {
                guard c.allSatisfy({ $0.isFinite && abs($0)<100000 }), let code=c.first else { throw NSError(domain:"Invalid outline",code:2) }
                switch Int(code) {
                case 0 where c.count==3: path.move(to:CGPoint(x:c[1],y:c[2]))
                case 1 where c.count==3: path.addLine(to:CGPoint(x:c[1],y:c[2]))
                case 2 where c.count==7: path.addCurve(to:CGPoint(x:c[5],y:c[6]),control1:CGPoint(x:c[1],y:c[2]),control2:CGPoint(x:c[3],y:c[4]))
                case 3 where c.count==1: path.closeSubpath()
                default: throw NSError(domain:"Invalid path command",code:3)
                }
            }
            p=OpticalSpacing.Profile(path.copy()!)
            if cache.count>2048 { cache.removeAll() }
            cache[g.shape]=p
        }
        var l=Letter();l.designCharacter=g.character;l.leftSpacingAdjustment=g.leftDelta;l.rightSpacingAdjustment=g.rightDelta
        var m=BodySpacing.metrics(p,letter:l,settings:settings,character:g.character)
        let oldLeft=m.left, oldRight=m.right
        if let fixed=g.left { m.left=fixed;m.fixedLeftAdjustment += fixed-oldLeft }
        if let fixed=g.right { m.right=fixed;m.fixedRightAdjustment += fixed-oldRight }
        m.advance=max(1,p.bounds.width+m.left+m.right)
        m.frameLeft = (m.frameLeft ?? oldLeft)+m.left-oldLeft
        m.frameRight = (m.frameRight ?? oldRight)+m.right-oldRight
        entries.append((g,p,m));results[g.name]=ResultGlyph(left:m.left,right:m.right,width:m.advance)
    }
    let context=try BodySpacing.context([(glyphs:entries.map { ($0.1,$0.2) },settings:settings)])
    let model=try r.contourPreset.map { try ContourSpacing.model($0) }
    let similarities=model.map { ContourSpacing.prepare(r.glyphs,r,$0) }
    // Candidate baseline is stock with no user bearing adjustments, exactly as
    // in the accepted research runtime. Manual edits must not be cancelled.
    var automatic: [String:OpticalSpacing.Metrics] = [:]
    if model != nil {
        for (g,p,_) in entries {
            var letter=Letter();letter.designCharacter=g.character
            var m=BodySpacing.metrics(p,letter:letter,settings:settings,character:g.character)
            m.advance=max(1,p.bounds.width+m.left+m.right)
            automatic[g.name]=m
        }
    }
    let changed=r.changed.map { Set($0) }
    var pairs: [String:Double] = [:]
    for (a,ap,am) in entries {
        for (b,bp,bm) in entries {
            if let changed, !changed.contains(a.name) && !changed.contains(b.name) { continue }
            if let model, let similarities {
                let stock=BodySpacing.kern(ap,automatic[a.name]!,bp,automatic[b.name]!,settings:settings,context:context)
                let preferred=stock+ContourSpacing.residual(similarities[a.name]!,similarities[b.name]!,model)
                pairs[a.name+"\t"+b.name]=ContourSpacing.protect(preferred,ap,am,bp,bm,settings)
            } else {
                pairs[a.name+"\t"+b.name]=BodySpacing.kern(ap,am,bp,bm,settings:settings,context:context)
            }
        }
    }
    return Reply(metrics:results,pairs:pairs,elapsedMS:Date().timeIntervalSince(start)*1000)
}
while let line=readLine() {
    do {
        let request=try JSONDecoder().decode(Request.self,from:Data(line.utf8))
        let result=try run(request)
        print(String(data:try JSONEncoder().encode(result),encoding:.utf8)!)
    } catch { print("{\"error\":\(String(data:try! JSONEncoder().encode(String(describing:error)),encoding:.utf8)!)}") }
    fflush(stdout)
}
