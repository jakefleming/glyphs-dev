import Foundation
import CoreGraphics
// Minimal input adapters. Geometry and optical calculations come from Graver.
struct FontSettings {
    var xHeight: Double; var capHeight: Double; var sidebearing: Double
    var slant: Double? = nil
    var spacingFactor: Double = 1
    var spacingEnabled = true
    var usesBodySpacing = true
    var kerningEnabled = true
    var kerningAmount: Double? = 1
    var protectsSpacingCollisions = true
    var opticalSpace: Double { sidebearing * spacingFactor }
}
struct Letter {
    var heightRole: String? = nil
    var designCharacter: String? = nil
    var sidebearingOverride: Double? = nil
    var leftSpacingAdjustment: Double? = nil
    var rightSpacingAdjustment: Double? = nil
}
enum ExportWork {
    static func map<A,B>(_ values: [A], _ fn: (A) throws -> B) rethrows -> [B] { try values.map(fn) }
}
