import Foundation

/// Reads an ingredient line the way a cook writes it:
/// "1 ½ cups (200 g) all-purpose flour, sifted", "2-3 cloves garlic",
/// "1 (15 oz) can black beans, drained", "salt and pepper to taste".
public enum IngredientParser {
    public static func parse(_ raw: String) -> RecipeIngredient {
        var line = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        // Bullets and checkboxes from captions and notes.
        while let f = line.first, "•-–—*▢☐▪◦·✓✔︎🔸🔹".contains(f) {
            line = String(line.dropFirst()).trimmingCharacters(in: .whitespaces)
        }
        let original = line

        // A note after the first comma: "onion, finely chopped".
        var note = ""
        if let comma = topLevelComma(in: line) {
            note = String(line[line.index(after: comma)...]).trimmingCharacters(in: .whitespaces)
            line = String(line[..<comma])
        }

        // Parentheses: an explicit size "(15 oz)" beats the count before it.
        var packSize: (Double, Unit)?
        var paren = ""
        while let open = line.firstIndex(of: "("), let close = line[open...].firstIndex(of: ")") {
            let inner = String(line[line.index(after: open)..<close])
            if packSize == nil, let s = sizeIn(inner) { packSize = s } else { paren += (paren.isEmpty ? "" : "; ") + inner }
            line.removeSubrange(open...close)
        }

        var tokens = tokenize(line)
        var amount: Double?
        var unit: Unit?

        // Leading number(s): "1 1/2", "1½", "2-3", "2 to 3".
        if let first = tokens.first, let v = Fraction.value(first) {
            amount = v
            tokens.removeFirst()
            if let next = tokens.first, let f = Fraction.value(next), next.contains("/") || Fraction.vulgar[next.last ?? " "] != nil, f < 1 {
                amount = v + f
                tokens.removeFirst()
            }
            if let next = tokens.first, ["-", "–", "to", "or"].contains(next), tokens.count > 1, let hi = Fraction.value(tokens[1]) {
                amount = (v + hi) / 2
                tokens.removeFirst(2)
            }
        } else if let first = tokens.first, let range = rangeValue(first) {
            amount = range
            tokens.removeFirst()
        } else if let first = tokens.first?.lowercased(), ["a", "an", "one"].contains(first) {
            amount = 1
            tokens.removeFirst()
        }

        // Unit word(s), allowing "fl oz".
        if tokens.count >= 2, Unit.parse(tokens[0] + " " + tokens[1]) == .floz {
            unit = .floz
            tokens.removeFirst(2)
        } else if let first = tokens.first, let u = Unit.parse(first), !(u == .each && amount == nil) {
            unit = u
            tokens.removeFirst()
            if tokens.first?.lowercased() == "of" { tokens.removeFirst() }
        }
        if amount == nil, unit == .pinch || unit == .dash { amount = 1 }

        // "1 (15 oz) can" → 15 oz; "2 (14 oz) cans" → 28 oz.
        // "1 ½ cups (200 g)": the weight in brackets is the more precise measure.
        if let (size, sizeUnit) = packSize {
            if unit == nil || unit == .can || unit == .pkg || unit == .each {
                amount = (amount ?? 1) * size
                unit = sizeUnit
            } else if sizeUnit.family == .mass, unit?.family == .volume {
                amount = size
                unit = sizeUnit
            }
        }

        var name = tokens.joined(separator: " ").trimmingCharacters(in: .whitespacesAndNewlines)
        if name.lowercased().hasPrefix("of ") { name = String(name.dropFirst(3)) }
        if amount != nil, unit == nil { unit = .each }
        let lower = name.lowercased()
        for tail in [" to taste", " as needed", " for serving", " for garnish", " optional"] where lower.hasSuffix(tail) {
            name = String(name.dropLast(tail.count))
            note = [note, tail.trimmingCharacters(in: .whitespaces)].filter { !$0.isEmpty }.joined(separator: ", ")
        }
        if !paren.isEmpty { note = [note, paren].filter { !$0.isEmpty }.joined(separator: "; ") }
        return RecipeIngredient(text: original, amount: amount, unit: unit, name: name.trimmingCharacters(in: .whitespaces), note: note)
    }

    private static func topLevelComma(in s: String) -> String.Index? {
        var depth = 0
        for i in s.indices {
            switch s[i] {
            case "(": depth += 1
            case ")": depth = max(0, depth - 1)
            case "," where depth == 0: return i
            default: break
            }
        }
        return nil
    }

    /// "15 oz", "400g", "14.5-ounce" inside parentheses.
    private static func sizeIn(_ s: String) -> (Double, Unit)? {
        let t = tokenize(s.replacingOccurrences(of: "-", with: " "))
        guard t.count >= 2, let v = Fraction.value(t[0]) else { return nil }
        if t.count >= 3, Unit.parse(t[1] + " " + t[2]) == .floz { return (v, .floz) }
        guard let u = Unit.parse(t[1]), u.family != .count else { return nil }
        return (v, u)
    }

    private static func rangeValue(_ token: String) -> Double? {
        for sep in ["-", "–"] where token.contains(sep) {
            let p = token.components(separatedBy: sep)
            if p.count == 2, let a = Fraction.value(p[0]), let b = Fraction.value(p[1]) { return (a + b) / 2 }
        }
        return nil
    }

    /// Splits "1½cups" → ["1½", "cups"], "200g" → ["200", "g"].
    static func tokenize(_ s: String) -> [String] {
        var out: [String] = []
        for raw in s.split(whereSeparator: { $0 == " " || $0 == "\t" }) {
            var word = String(raw)
            if word.isEmpty { continue }
            // Split a number glued to a unit.
            if let idx = word.firstIndex(where: { $0.isLetter }), idx != word.startIndex {
                let num = String(word[..<idx])
                let rest = String(word[idx...])
                if Fraction.value(num) != nil || rangeValue(num) != nil, Unit.parse(rest) != nil {
                    out.append(num)
                    word = rest
                }
            }
            out.append(word)
        }
        return out
    }
}

/// Finds the catalog ingredient a line is about, and converts its amount
/// into that ingredient's base unit.
public struct Catalog: Sendable {
    public let items: [String: Ingredient]
    private let index: [(alias: String, id: String, words: Set<String>)]
    private let forms: [String: Form]

    /// How a thing is sold. "A can of black beans" and "dried black beans"
    /// read the same once cooking words are gone, but differ 4× in calories.
    public enum Form: Sendable { case plain, canned, dried, frozen }

    public init(_ list: [Ingredient]) {
        var items: [String: Ingredient] = [:]
        var forms: [String: Form] = [:]
        var index: [(String, String, Set<String>)] = []
        for i in list {
            items[i.id] = i
            let named = Catalog.words(i.name)
            forms[i.id] = i.aisle == .canned ? .canned : i.aisle == .frozen ? .frozen
                : named.contains("dried") || named.contains("dry") ? .dried : .plain
            for a in Set([i.name.lowercased()] + i.aliases.map { $0.lowercased() }) { index.append((Catalog.normalize(a), i.id, Catalog.words(a))) }
        }
        // Longest first, so "chicken thigh" wins over "chicken"; ties settle the same way every time.
        self.items = items
        self.forms = forms
        self.index = index.sorted { $0.0.count != $1.0.count ? $0.0.count > $1.0.count : ($0.1, $0.0) < ($1.1, $1.0) }
    }

    /// The words as written, singular — cooking words kept.
    static func words(_ s: String) -> Set<String> {
        Set(s.lowercased().replacingOccurrences(of: "-", with: " ").split { !$0.isLetter }.map { singular(String($0)) })
    }

    /// How a recipe line says it's bought: "1 (15 oz) can black beans" → canned.
    public static func form(of text: String, unit: Unit? = nil) -> Form {
        if unit == .can { return .canned }
        let w = words(text)
        if !w.isDisjoint(with: ["can", "canned", "tin", "tinned"]) { return .canned }
        if w.contains("frozen") { return .frozen }
        if w.contains("dried") || w.contains("dry") { return .dried }
        return .plain
    }

    /// How well a catalog item's form suits what the line asked for.
    private static func fit(_ wanted: Form, _ item: Form) -> Int {
        if wanted == item { return 3 }
        switch (wanted, item) {
        case (.plain, .canned): return 2      // "1 cup chickpeas" is canned, not dried
        case (.plain, .frozen): return 1
        case (_, .plain): return 1            // "dried oregano" is just oregano
        default: return 0
        }
    }

    public subscript(_ id: String) -> Ingredient? { items[id] }

    static let noise: Set<String> = [
        "fresh", "freshly", "chopped", "finely", "roughly", "diced", "minced", "sliced", "thinly", "large", "small", "medium", "boneless",
        "skinless", "ground", "grated", "shredded", "crushed", "peeled", "cooked", "uncooked", "dried", "dry", "raw", "ripe", "organic",
        "of", "the", "and", "or", "about", "plus", "more", "extra", "virgin", "packed", "lightly", "heaping", "level", "whole", "halved",
        "quartered", "cubed", "rinsed", "drained", "softened", "melted", "room", "temperature", "cold", "warm", "low", "sodium",
        "reduced", "lean", "good", "quality", "store", "bought", "homemade", "canned", "thawed", "trimmed", "into", "cut",
        "pieces", "piece", "inch", "inches", "for", "serving", "garnish", "optional", "a", "an", "few", "handful", "some",
    ]

    /// Lower-case, singular, without cooking words: "Finely Chopped Onions" → "onion".
    public static func normalize(_ s: String) -> String {
        let cleaned = s.lowercased()
            .replacingOccurrences(of: "-", with: " ")
            .replacingOccurrences(of: "’", with: "'")
            .components(separatedBy: CharacterSet.letters.union(.whitespaces).union(CharacterSet(charactersIn: "'")).inverted).joined(separator: " ")
        let words = cleaned.split(separator: " ").map(String.init).filter { !noise.contains($0) }.map(singular)
        return words.joined(separator: " ")
    }

    static func singular(_ w: String) -> String {
        let irregular = ["tomatoes": "tomato", "potatoes": "potato", "leaves": "leaf", "loaves": "loaf", "halves": "half",
                         "chilies": "chili", "chillies": "chili", "berries": "berry", "cherries": "cherry", "anchovies": "anchovy"]
        if let i = irregular[w] { return i }
        if w.count > 4, w.hasSuffix("ies") { return String(w.dropLast(3)) + "y" }
        if w.count > 3, w.hasSuffix("oes") { return String(w.dropLast(2)) }
        if w.count > 3, w.hasSuffix("s"), !w.hasSuffix("ss"), !w.hasSuffix("us"), !w.hasSuffix("is") { return String(w.dropLast()) }
        return w
    }

    /// The best catalog match for an ingredient name, if any. Among the
    /// longest matching names it prefers the form the line asks for (canned,
    /// dried, frozen), then the one sharing most of the line's own words
    /// ("crushed" vs "diced" tomatoes).
    public func match(_ name: String, form: Form = .plain, words: Set<String> = []) -> Ingredient? {
        let n = " " + Catalog.normalize(name) + " "
        guard n.trimmingCharacters(in: .whitespaces).count > 1 else { return nil }
        var length: Int?
        var best: (fit: Int, shared: Int, id: String)?
        for e in index {
            if let length, e.alias.count < length { break }
            guard n.contains(" " + e.alias + " ") else { continue }
            length = e.alias.count
            let f = Catalog.fit(form, forms[e.id] ?? .plain), shared = e.words.intersection(words).count
            if best == nil || (f, shared) > (best!.fit, best!.shared) { best = (f, shared, e.id) }
        }
        return best.flatMap { items[$0.id] }
    }

    /// The best match for a whole recipe line, using how it's bought.
    public func match(_ line: RecipeIngredient) -> Ingredient? {
        let text = line.text.isEmpty ? line.name : line.text
        return match(line.name, form: Catalog.form(of: text, unit: line.unit), words: Catalog.words(text))
    }

    /// Fills in `ingredientID` for every line it recognises.
    public func resolve(_ r: Recipe) -> Recipe {
        var r = r
        for i in r.ingredients.indices where r.ingredients[i].ingredientID == nil {
            r.ingredients[i].ingredientID = match(r.ingredients[i])?.id
        }
        return r
    }

    /// The line's amount in the ingredient's base unit (grams or pieces).
    public func baseAmount(_ line: RecipeIngredient, scale: Double = 1) -> Double? {
        guard let id = line.ingredientID, let ing = items[id], let amount = line.amount else { return nil }
        let unit = line.unit ?? .each
        let a = amount * scale
        switch (ing.base, unit.family) {
        case (.g, .mass):
            return a * unit.factor
        case (.g, .volume):
            guard let gpc = ing.gramsPerCup else { return a * unit.factor }   // ~water density
            return a * unit.factor / Unit.cup.factor * gpc
        case (.g, .count):
            let smallest = ing.packages.map(\.amount).min()
            if unit == .stick { return a * 113 }          // butter
            if unit == .bunch, let ge = ing.gramsEach { return a * ge }
            if unit == .clove { return a * (ing.gramsEach ?? 5) }
            if unit == .can || unit == .pkg { return a * (smallest ?? 425) }   // "1 can", "1 packet": the size it's sold in
            if unit == .slice { return a * (ing.gramsEach ?? 28) }
            return a * (ing.gramsEach ?? 100)
        case (.each, .count):
            if unit == .clove, ing.id == "garlic" { return a / 10 }   // ~10 cloves a head
            return a
        case (.each, .mass):
            guard let ge = ing.gramsEach else { return a }
            return a * unit.factor / ge
        case (.each, .volume):
            guard let ge = ing.gramsEach, let gpc = ing.gramsPerCup else { return a }
            return a * unit.factor / Unit.cup.factor * gpc / ge
        }
    }
}
