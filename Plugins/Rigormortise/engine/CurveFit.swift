import Foundation
import CoreGraphics

/// Error-bounded least-squares cubic fitting. Raw input samples remain in the project.
enum CurveFit {
    struct Cubic {
        var p0: CGPoint; var p1: CGPoint; var p2: CGPoint; var p3: CGPoint
        func point(_ t: Double) -> CGPoint {
            let u = 1-t
            return add(add(mul(p0,u*u*u),mul(p1,3*u*u*t)),add(mul(p2,3*u*t*t),mul(p3,t*t*t)))
        }
    }
    static func add(_ a: CGPoint,_ b: CGPoint) -> CGPoint { CGPoint(x:a.x+b.x,y:a.y+b.y) }
    static func sub(_ a: CGPoint,_ b: CGPoint) -> CGPoint { CGPoint(x:a.x-b.x,y:a.y-b.y) }
    static func mul(_ a: CGPoint,_ n: Double) -> CGPoint { CGPoint(x:a.x*n,y:a.y*n) }
}
