import Foundation
import CoreGraphics

/// The reviewed contour model. Names identify results, never geometric features.
/// Stock is unchanged unless an explicit model is supplied by the preview UI.
struct ContourModel: Decodable {
    struct Parameters: Decodable { let sigma: Double; let interaction: Double }
    struct Member: Decodable {
        let mode: String
        let parameters: Parameters
        let alpha: [Double]
        let rightContours: [[Double]]
        let leftContours: [[Double]]
    }
    let mode: String
    let stockSpace: Double
    let weights: [Double]
    let members: [Member]
    func validate() throws {
        guard mode == "contour-ensemble", weights.count == members.count, members.count <= 4,
              weights.allSatisfy({ $0.isFinite && $0 >= 0 }), abs(weights.reduce(0,+)-1)<0.00001 else {
            throw NSError(domain:"Invalid contour ensemble",code:20)
        }
        for m in members {
            guard m.mode == "geometry-kernel", m.parameters.sigma.isFinite, m.parameters.sigma > 0,
                  m.parameters.interaction.isFinite, m.parameters.interaction >= 0,
                  m.alpha.count <= 1000, !m.alpha.isEmpty,
                  m.alpha.allSatisfy({ $0.isFinite }), m.rightContours.count == m.alpha.count,
                  m.leftContours.count == m.alpha.count,
                  (m.rightContours+m.leftContours).allSatisfy({ $0.count == 164 && $0.allSatisfy({ $0.isFinite }) }) else {
                throw NSError(domain:"Invalid contour samples",code:21)
            }
        }
    }
}

enum ContourSpacing {
    struct Sides { let left: [Double]; let right: [Double] }
    private static var descriptors: [String:Sides] = [:]
    private static var models: [String:ContourModel] = [:]
    static func model(_ name: String) throws -> ContourModel {
        guard ["saddleshoe-regular-v3","saddleshoe-black-v3"].contains(name) else {
            throw NSError(domain:"Unknown contour preset",code:22)
        }
        if let known=models[name] { return known }
        let directory=URL(fileURLWithPath:CommandLine.arguments[0]).deletingLastPathComponent()
        let value=try JSONDecoder().decode(ContourModel.self,from:Data(contentsOf:directory.appendingPathComponent("models/\(name).json")))
        try value.validate(); models[name]=value;return value
    }
    static func sides(_ glyph: InputGlyph, _ request: Request) -> Sides {
        let key="\(glyph.shape)|\(request.xHeight)|\(request.slant)"
        if let known=descriptors[key] { return known }
        var edges: [(CGPoint,CGPoint)] = []
        var current=CGPoint.zero, start=CGPoint.zero
        let shear=tan(max(-30,min(30,request.slant)) * .pi/180)
        func upright(_ p: CGPoint) -> CGPoint { CGPoint(x:p.x-p.y*shear,y:p.y) }
        func edge(_ a: CGPoint,_ b: CGPoint) { edges.append((upright(a),upright(b))) }
        // Commands have already passed the engine's validation.
        for c in glyph.commands {
            switch Int(c[0]) {
            case 0: current=CGPoint(x:c[1],y:c[2]);start=current
            case 1: let end=CGPoint(x:c[1],y:c[2]);edge(current,end);current=end
            case 2:
                let p=CGPoint(x:c[1],y:c[2]), q=CGPoint(x:c[3],y:c[4]), end=CGPoint(x:c[5],y:c[6])
                let from=current
                for i in 1...64 {
                    let t=Double(i)/64, u=1-t
                    let next=CGPoint(x:u*u*u*from.x+3*u*u*t*p.x+3*u*t*t*q.x+t*t*t*end.x,
                                     y:u*u*u*from.y+3*u*u*t*p.y+3*u*t*t*q.y+t*t*t*end.y)
                    edge(current,next);current=next
                }
                current=end
            case 3: edge(current,start);current=start
            default: break
            }
        }
        let points=edges.flatMap { [$0.0,$0.1] }
        let xmin=points.map(\.x).min() ?? 0, xmax=points.map(\.x).max() ?? 0
        let ymin=points.map(\.y).min() ?? 0, ymax=points.map(\.y).max() ?? 0
        let h=request.xHeight
        var left=[Double](),right=[Double](),mask=[Double]()
        for i in 0...80 {
            let y=(-0.4+Double(i)*0.025)*h
            var low=Double.infinity,high = -Double.infinity
            for (a,b) in edges where (a.y <= y && b.y > y) || (b.y <= y && a.y > y) {
                let x=a.x+(y-a.y)*(b.x-a.x)/(b.y-a.y)
                low=min(low,x);high=max(high,x)
            }
            if low.isFinite { left.append(min(1.5,(low-xmin)/h));right.append(min(1.5,(xmax-high)/h));mask.append(0) }
            else { left.append(0);right.append(0);mask.append(0.5) }
        }
        let common=mask+[ymin/h,ymax/h]
        let result=Sides(left:left+common,right:right+common)
        if descriptors.count>4096 { descriptors.removeAll() }
        descriptors[key]=result;return result
    }
    struct Similarities { let left: [[Double]]; let right: [[Double]] }
    static func prepare(_ glyphs: [InputGlyph],_ request: Request,_ model: ContourModel) -> [String:Similarities] {
        var result: [String:Similarities] = [:]
        for g in glyphs {
            let shape=sides(g,request)
            var ls=[[Double]](),rs=[[Double]]()
            for member in model.members {
                let scale=1/(164*2*member.parameters.sigma*member.parameters.sigma)
                func similarity(_ side: [Double],_ samples: [[Double]]) -> [Double] {
                    samples.map { sample in
                        var squared=0.0
                        for i in 0..<164 { let d=side[i]-sample[i];squared+=d*d }
                        return exp(-squared*scale)
                    }
                }
                ls.append(similarity(shape.left,member.leftContours));rs.append(similarity(shape.right,member.rightContours))
            }
            result[g.name]=Similarities(left:ls,right:rs)
        }
        return result
    }
    static func residual(_ a: Similarities,_ b: Similarities,_ model: ContourModel) -> Double {
        var result=0.0
        for j in model.members.indices {
            let m=model.members[j];var value=0.0
            for i in m.alpha.indices {
                let r=a.right[j][i],l=b.left[j][i]
                value+=(r+l+m.parameters.interaction*r*l)*m.alpha[i]
            }
            result+=model.weights[j]*value
        }
        return result
    }
    /// Reapply the research candidate's independent clearance and punctuation
    /// guards after the residual. Bearing adjustments remain additive.
    static func protect(_ preferred: Double,_ a: OpticalSpacing.Profile,_ am: OpticalSpacing.Metrics,
                        _ b: OpticalSpacing.Profile,_ bm: OpticalSpacing.Metrics,_ s: FontSettings) -> Double {
        let existing=am.advance-a.bounds.width-am.left+bm.left
        var nearest: Double?
        a.sharedRows(b) { _,right,left in
            let gap=a.bounds.maxX-right+left-b.bounds.minX
            nearest=min(nearest ?? gap,gap)
        }
        guard nearest != nil else { return ceil(preferred) }
        let punctuation=am.punctuation != .none || bm.punctuation != .none
        var floor = -Double.infinity, optical=preferred
        if let closest=nearest, s.protectsSpacingCollisions {
            floor=BodySpacing.minimum(settings:s,punctuation:punctuation)-closest-existing
        }
        if punctuation {
            let space=max(0,s.opticalSpace)
            optical=max(optical,-space*(am.punctuation == .sentence || bm.punctuation == .sentence ? 0.6 : 1))
            let widths=[(am,a),(bm,b)].compactMap { m,p in m.punctuation == .none ? nil : max(0,m.frameWidth ?? p.bounds.width) }
            let overlap=min(space*0.5,(widths.min() ?? 0)*0.25)
            let frameGap=(am.frameRight ?? (am.advance-a.bounds.width-am.left))+(bm.frameLeft ?? bm.left)
            floor=max(floor,-overlap-frameGap)
        }
        return ceil(max(optical,floor))
    }
}
