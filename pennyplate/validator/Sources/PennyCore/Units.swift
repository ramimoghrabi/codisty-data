import Foundation

/// Kitchen units. Every amount is turned into an ingredient's base unit
/// (grams, or "each" for things bought by the piece) before it's priced.
public enum Unit: String, Codable, CaseIterable, Sendable {
    // volume
    case tsp, tbsp, cup, floz, ml, l, pint, quart
    // mass
    case g, kg, oz, lb
    // count-ish
    case each, clove, slice, can, bunch, pinch, dash, stick, pkg, head, sprig

    public enum Family: Sendable { case volume, mass, count }

    public var family: Family {
        switch self {
        case .tsp, .tbsp, .cup, .floz, .ml, .l, .pint, .quart: return .volume
        case .g, .kg, .oz, .lb: return .mass
        default: return .count
        }
    }

    /// Millilitres per unit (volume) or grams per unit (mass).
    public var factor: Double {
        switch self {
        case .tsp: return 4.929
        case .tbsp: return 14.787
        case .cup: return 236.588
        case .floz: return 29.574
        case .ml: return 1
        case .l: return 1000
        case .pint: return 473.176
        case .quart: return 946.353
        case .g: return 1
        case .kg: return 1000
        case .oz: return 28.3495
        case .lb: return 453.592
        case .pinch: return 0.36      // ≈ 1/16 tsp, in ml
        case .dash: return 0.6
        default: return 1
        }
    }

    /// Spelled-out forms people type, in recipes and captions.
    static let aliases: [String: Unit] = {
        var m: [String: Unit] = [:]
        let table: [(Unit, [String])] = [
            (.tsp, ["tsp", "tsps", "teaspoon", "teaspoons", "t", "tspn"]),
            (.tbsp, ["tbsp", "tbsps", "tablespoon", "tablespoons", "tbs", "tbl", "tbl.", "T"]),
            (.cup, ["cup", "cups", "c"]),
            (.floz, ["fl oz", "fl. oz", "fluid ounce", "fluid ounces", "floz"]),
            (.ml, ["ml", "milliliter", "milliliters", "millilitre", "millilitres", "mls"]),
            (.l, ["l", "liter", "liters", "litre", "litres"]),
            (.pint, ["pint", "pints", "pt"]),
            (.quart, ["quart", "quarts", "qt"]),
            (.g, ["g", "gram", "grams", "gr", "grs"]),
            (.kg, ["kg", "kilogram", "kilograms", "kilo", "kilos"]),
            (.oz, ["oz", "ounce", "ounces", "oz."]),
            (.lb, ["lb", "lbs", "pound", "pounds", "lb.", "lbs."]),
            (.clove, ["clove", "cloves"]),
            (.slice, ["slice", "slices"]),
            (.can, ["can", "cans", "tin", "tins"]),
            (.bunch, ["bunch", "bunches"]),
            (.pinch, ["pinch", "pinches"]),
            (.dash, ["dash", "dashes"]),
            (.stick, ["stick", "sticks"]),
            (.pkg, ["package", "packages", "pkg", "pkgs", "packet", "packets", "pack", "packs", "bag", "bags", "box", "boxes", "jar", "jars"]),
            (.head, ["head", "heads"]),
            (.sprig, ["sprig", "sprigs"]),
            (.each, ["each", "piece", "pieces", "whole", "large", "medium", "small", "x"]),
        ]
        for (u, words) in table { for w in words { m[w] = u } }
        return m
    }()

    /// Case matters for the classic "T" (tablespoon) vs "t" (teaspoon).
    public static func parse(_ word: String) -> Unit? {
        if word == "T" || word == "Tbsp" || word == "TBSP" { return .tbsp }
        if word == "t" { return .tsp }
        let w = word.lowercased().trimmingCharacters(in: CharacterSet(charactersIn: "."))
        return aliases[w] ?? aliases[w + "."]
    }

    /// The short label shown in the app.
    public var label: String {
        switch self {
        case .tsp: return "tsp"
        case .tbsp: return "tbsp"
        case .cup: return "cup"
        case .floz: return "fl oz"
        case .ml: return "ml"
        case .l: return "L"
        case .pint: return "pint"
        case .quart: return "quart"
        case .g: return "g"
        case .kg: return "kg"
        case .oz: return "oz"
        case .lb: return "lb"
        case .each: return ""
        case .clove: return "clove"
        case .slice: return "slice"
        case .can: return "can"
        case .bunch: return "bunch"
        case .pinch: return "pinch"
        case .dash: return "dash"
        case .stick: return "stick"
        case .pkg: return "pack"
        case .head: return "head"
        case .sprig: return "sprig"
        }
    }
}

/// How an ingredient is measured when bought.
public enum BaseUnit: String, Codable, Sendable { case g, each }

/// "1 ½", "1/3", "0.25" and friends.
public enum Fraction {
    static let vulgar: [Character: Double] = [
        "½": 0.5, "⅓": 1.0 / 3, "⅔": 2.0 / 3, "¼": 0.25, "¾": 0.75, "⅕": 0.2, "⅖": 0.4, "⅗": 0.6, "⅘": 0.8,
        "⅙": 1.0 / 6, "⅚": 5.0 / 6, "⅛": 0.125, "⅜": 0.375, "⅝": 0.625, "⅞": 0.875,
    ]

    /// Parses one number token: "2", "1.5", "1/2", "½", "1½".
    public static func value(_ token: String) -> Double? {
        let t = token.replacingOccurrences(of: ",", with: ".")
        if let d = Double(t) { return d }
        var rest = Substring(t)
        if let last = rest.last, let v = vulgar[last] {
            rest = rest.dropLast()
            if rest.isEmpty { return v }
            guard let w = Double(rest) else { return nil }
            return w + v
        }
        let parts = t.split(separator: "/")
        if parts.count == 2, let n = Double(parts[0]), let d = Double(parts[1]), d != 0 {
            return n / d
        }
        return nil
    }

    /// The way a cook reads it: 0.5 → "½", 1.333 → "1 ⅓", 2 → "2".
    public static func pretty(_ v: Double) -> String {
        guard v > 0 else { return "0" }
        if v >= 10 { return String(Int(v.rounded())) }
        let whole = Int(v)
        let frac = v - Double(whole)
        let options: [(Double, String)] = [(0, ""), (0.125, "⅛"), (0.25, "¼"), (1.0 / 3, "⅓"), (0.5, "½"),
                                           (2.0 / 3, "⅔"), (0.75, "¾"), (1, "")]
        let best = options.min { abs($0.0 - frac) < abs($1.0 - frac) }!
        if best.0 == 1 { return String(whole + 1) }
        if best.1.isEmpty { return whole == 0 ? "0" : String(whole) }
        return whole == 0 ? best.1 : "\(whole) \(best.1)"
    }
}
