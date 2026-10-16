import Foundation
import PennyCore

// pennycheck — the gate every recipe passes before the app can see it.
//
//   pennycheck check  --catalog C --recipes R
//       Checks the published file. Exits 1 on anything that would break the
//       app or mislabel a diet; price drift only warns.
//
//   pennycheck screen --catalog C --recipes R --candidates X --out O
//       Screens new candidates (a JSON array of recipes) against the catalog
//       and the published recipes. Writes {"accepted": [...], "rejected": [...]}
//       with the reasons, so the generator can ask for fixes.
//
// It uses the app's own parser, matcher and costing (Sources/PennyCore), so a
// recipe that passes here reads and prices exactly the same on the phone.

struct Args {
    var command = ""
    var options: [String: String] = [:]

    init() {
        var it = CommandLine.arguments.dropFirst().makeIterator()
        command = it.next() ?? ""
        while let a = it.next() {
            guard a.hasPrefix("--") else { continue }
            options[String(a.dropFirst(2))] = it.next() ?? ""
        }
    }

    func path(_ key: String) -> URL {
        guard let p = options[key] else { fail("missing --\(key)") }
        return URL(fileURLWithPath: p)
    }
}

func fail(_ message: String) -> Never {
    FileHandle.standardError.write(Data("pennycheck: \(message)\n".utf8))
    exit(2)
}

// MARK: - rules

enum Rules {
    static let tints: Set<String> = ["tomato", "amber", "sage", "lime", "berry", "clay", "olive", "sea", "plum"]

    /// Catalog ids that rule a diet out. Text checks below catch the rest
    /// ("chicken broth" and "vegetable broth" share an id).
    static let meatIDs: Set<String> = ["fish-sauce", "oyster-sauce", "worcestershire"]
    static let animalIDs: Set<String> = ["egg", "honey", "mayo", "labneh", "halloumi-fresh", "biscuits", "pesto", "buns",
                                         "egg-noodles", "chocolate-chips", "frozen-pizza-dough"]
    static let dairyIDs: Set<String> = ["labneh", "halloumi-fresh", "biscuits", "pesto", "chocolate-chips"]
    static let glutenIDs: Set<String> = ["flour", "pasta", "lasagna", "egg-noodles", "ramen", "orzo", "couscous", "bulgur", "breadcrumbs",
                                         "bread", "flour-tortilla", "pita", "buns", "frozen-pizza-dough", "biscuits", "soy-sauce",
                                         "teriyaki", "oyster-sauce", "miso", "oats"]
    static let meatWords = ["chicken", "beef", "pork", "bacon", "lamb", "turkey", "sausage", "anchov", "gelatin", " lard", "prosciutto",
                            "pepperoni", "chorizo", "veal", "bone broth"]
    static let fishWords = ["fish", "shrimp", "prawn", "salmon", "tuna", "cod", "tilapia", "anchov", "crab", "clam", "mussel"]
    static let dairyWords = ["butter", "cheese", "cream", "milk", "yogurt", "yoghurt", "ghee", "whey", "labneh", "parmesan", "feta"]
    static let plantDairyWords = ["plant milk", "oat milk", "almond milk", "soy milk", "coconut milk", "coconut cream", "vegan butter",
                                  "nutritional yeast", "peanut butter", "almond butter", "cocoa butter", "cream of tartar", "butternut",
                                  "butter bean", "butter lettuce"]
    static let glutenWords = ["flour", "wheat", "barley", " rye", "panko", "breadcrumb", "noodle", "couscous", "bulgur", "pita", "tortilla",
                              "spaghetti", "macaroni", "penne", "farro", "seitan"]
    static let glutenFreeWords = ["gluten-free", "gluten free", "corn tortilla", "rice noodle", "rice flour", "almond flour", "chickpea flour", "tamari",
                                  "tortilla chip", "cornflour", "corn flour"]

    static func normalTitle(_ t: String) -> String {
        t.lowercased().unicodeScalars.filter { CharacterSet.alphanumerics.contains($0) }.map(String.init).joined()
    }

    static func words(_ t: String) -> Set<String> {
        let stop: Set<String> = ["and", "with", "the", "a", "of", "in", "on", "style", "easy", "quick"]
        return Set(t.lowercased().split { !$0.isLetter }.map(String.init).filter { $0.count > 2 && !stop.contains($0) })
    }

    struct Report {
        var errors: [String] = []
        var warnings: [String] = []
    }

    static func check(_ a: Library.Authored, against others: [Library.Authored], catalog: Catalog, strictPrices: Bool) -> Report {
        var rep = Report()
        func err(_ s: String) { rep.errors.append(s) }
        func price(_ s: String) { strictPrices ? rep.errors.append(s) : rep.warnings.append(s) }

        // identity
        if a.id.range(of: "^[a-z0-9]+(-[a-z0-9]+)*$", options: .regularExpression) == nil || a.id.count > 60 {
            err("id must be lowercase-words-with-hyphens (got \"\(a.id)\")")
        }
        if others.contains(where: { $0.id == a.id }) { err("id \"\(a.id)\" is already taken") }
        if !(3...60).contains(a.title.count) { err("title should be 3–60 characters") }
        let nt = normalTitle(a.title), tw = words(a.title)
        if let twin = others.first(where: { normalTitle($0.title) == nt }) {
            err("title duplicates \"\(twin.title)\"")
        } else if tw.count >= 2, let twin = others.first(where: { o in
            let ow = words(o.title)
            return !ow.isEmpty && Double(tw.intersection(ow).count) / Double(tw.union(ow).count) >= 0.75
        }) {
            err("title is too close to \"\(twin.title)\"")
        }
        if !(20...220).contains(a.summary.count) { err("summary should be one sentence of 20–220 characters") }

        // shape
        if !(2...8).contains(a.servings) { err("servings should be 2–8") }
        if !(5...600).contains(a.minutes) { err("minutes should be 5–600") }
        if !(1...6).contains(a.keepsDays) { err("keepsDays should be 1–6") }
        if !(3...18).contains(a.ingredients.count) { err("use 3–18 ingredient lines") }
        if !(3...12).contains(a.steps.count) { err("use 3–12 steps") }
        if a.steps.contains(where: { $0.count < 12 || $0.count > 600 }) { err("every step should be a full sentence (12–600 characters)") }
        if a.equipment.isEmpty { err("list the equipment") }
        if !tints.contains(a.tint) { err("tint must be one of \(tints.sorted().joined(separator: ", "))") }
        if a.emoji.count != 1 || !(a.emoji.unicodeScalars.first?.properties.isEmoji ?? false) { err("emoji must be a single emoji") }
        if a.tags.count > 6 || a.tags.contains(where: { $0 != $0.lowercased() || $0.isEmpty }) { err("up to 6 lowercase tags") }
        if Set(a.diets).count != a.diets.count { err("diets has duplicates") }

        // every line read and priced the way the app will
        let recipe = Library.recipes(Library.RecipeFile(version: 0, updated: "", recipes: [a]), catalog: catalog)[0]
        let unmatched = recipe.ingredients.filter { $0.ingredientID == nil }.map(\.text)
        for line in unmatched { err("ingredient not in the catalog: \"\(line)\"") }
        guard unmatched.isEmpty else { return rep }

        let costing = Costing(catalog: catalog, household: Household())
        let c = costing.cost(recipe)
        for (i, cost) in c.lines where cost <= 0 {
            let line = recipe.ingredients[i]
            if let id = line.ingredientID, catalog[id]?.staple == false {
                err("can't price \"\(line.text)\" — give an amount in a unit that fits \(catalog[id]?.name ?? id)")
            }
        }
        let floor = a.meal == .dinner ? 0.45 : 0.2
        if c.perServing < floor { price(String(format: "$%.2f a serving is implausibly cheap — check the amounts", c.perServing)) }
        if c.perServing > 6.5 { price(String(format: "$%.2f a serving is too dear for a budget app (max $6.50)", c.perServing)) }
        if c.kcalPerServing < 150 { err(String(format: "%.0f kcal a serving is too light for a meal — check the amounts", c.kcalPerServing)) }
        if c.kcalPerServing > 1400 { err(String(format: "%.0f kcal a serving is too heavy — check the amounts", c.kcalPerServing)) }
        if a.diets.contains(.highProtein), c.proteinPerServing < 20 {
            err(String(format: "labelled highProtein but only %.0f g protein a serving (needs 20+)", c.proteinPerServing))
        }

        // diets are promises: check them against what's actually in it
        let lines = recipe.ingredients.map { (id: $0.ingredientID ?? "", text: " " + $0.text.lowercased() + " ", aisle: catalog[$0.ingredientID ?? ""]?.aisle) }
        func has(_ test: ((id: String, text: String, aisle: Aisle?)) -> Bool) -> [String] { lines.filter(test).map { $0.text.trimmingCharacters(in: .whitespaces) } }
        func mentions(_ text: String, _ words: [String]) -> Bool { words.contains { text.contains($0) } }
        let isMeat: ((id: String, text: String, aisle: Aisle?)) -> Bool = { l in
            l.aisle == .meat || meatIDs.contains(l.id) || mentions(l.text, meatWords)
        }
        let isFish: ((id: String, text: String, aisle: Aisle?)) -> Bool = { l in l.aisle == .seafood || mentions(l.text, fishWords) }
        let isDairy: ((id: String, text: String, aisle: Aisle?)) -> Bool = { l in
            if l.id == "plant-milk" || l.id == "coconut-milk" || mentions(l.text, plantDairyWords) { return false }
            return (l.aisle == .dairy && l.id != "egg") || dairyIDs.contains(l.id) || mentions(l.text, dairyWords)
        }
        let isAnimal: ((id: String, text: String, aisle: Aisle?)) -> Bool = { l in isMeat(l) || isFish(l) || isDairy(l) || animalIDs.contains(l.id) }
        let isGluten: ((id: String, text: String, aisle: Aisle?)) -> Bool = { l in
            if mentions(l.text, glutenFreeWords) { return false }
            return glutenIDs.contains(l.id) || mentions(l.text, glutenWords)
        }
        for d in a.diets {
            let bad: [String]
            switch d {
            case .vegetarian: bad = has { isMeat($0) || isFish($0) }
            case .vegan: bad = has(isAnimal)
            case .pescatarian: bad = has(isMeat)
            case .dairyFree: bad = has(isDairy)
            case .glutenFree: bad = has(isGluten)
            case .highProtein: bad = []
            }
            for line in bad { err("labelled \(d.rawValue) but has \"\(line)\"") }
        }
        return rep
    }
}

// MARK: - files

func loadCatalog(_ url: URL) -> Catalog {
    guard let data = try? Data(contentsOf: url) else { fail("can't read \(url.path)") }
    do { return Catalog(try Library.catalog(data).items) } catch { fail("catalog doesn't decode: \(error)") }
}

func loadRecipes(_ url: URL) -> Library.RecipeFile {
    guard let data = try? Data(contentsOf: url) else { fail("can't read \(url.path)") }
    do { return try Library.recipeFile(data) } catch { fail("recipes don't decode: \(error)") }
}

/// Decodes candidates one at a time so one bad recipe doesn't sink the rest.
func loadCandidates(_ url: URL) -> [(raw: Any, recipe: Library.Authored?, error: String?)] {
    guard let data = try? Data(contentsOf: url), let list = try? JSONSerialization.jsonObject(with: data) as? [Any] else {
        fail("candidates must be a JSON array")
    }
    return list.map { raw in
        do {
            let d = try JSONSerialization.data(withJSONObject: raw)
            return (raw, try JSONDecoder().decode(Library.Authored.self, from: d), nil)
        } catch let DecodingError.dataCorrupted(c) {
            return (raw, nil, "doesn't decode: \(c.debugDescription) at \(c.codingPath.map(\.stringValue).joined(separator: "."))")
        } catch let DecodingError.keyNotFound(k, _) {
            return (raw, nil, "missing field \"\(k.stringValue)\"")
        } catch let DecodingError.typeMismatch(_, c) {
            return (raw, nil, "wrong type at \(c.codingPath.map(\.stringValue).joined(separator: "."))")
        } catch {
            return (raw, nil, "doesn't decode: \(error)")
        }
    }
}

// MARK: - commands

let args = Args()
switch args.command {
case "check":
    let catalog = loadCatalog(args.path("catalog"))
    let file = loadRecipes(args.path("recipes"))
    var errors = 0, warnings = 0
    for (i, r) in file.recipes.enumerated() {
        var others = file.recipes
        others.remove(at: i)
        let rep = Rules.check(r, against: others, catalog: catalog, strictPrices: false)
        for e in rep.errors { print("ERROR  \(r.id): \(e)") }
        for w in rep.warnings { print("warn   \(r.id): \(w)") }
        errors += rep.errors.count
        warnings += rep.warnings.count
    }
    print("\(file.recipes.count) recipes · \(errors) errors · \(warnings) warnings")
    exit(errors == 0 ? 0 : 1)

case "screen":
    let catalog = loadCatalog(args.path("catalog"))
    var known = loadRecipes(args.path("recipes")).recipes
    var accepted: [Any] = []
    var rejected: [[String: Any]] = []
    var stats: [String: Any] = [:]
    for c in loadCandidates(args.path("candidates")) {
        let title = (c.raw as? [String: Any])?["title"] as? String ?? "?"
        guard let r = c.recipe else {
            rejected.append(["title": title, "reasons": [c.error ?? "doesn't decode"]])
            continue
        }
        let rep = Rules.check(r, against: known, catalog: catalog, strictPrices: true)
        if rep.errors.isEmpty {
            let recipe = Library.recipes(Library.RecipeFile(version: 0, updated: "", recipes: [r]), catalog: catalog)[0]
            let cost = Costing(catalog: catalog, household: Household()).cost(recipe)
            stats[r.id] = ["perServing": (cost.perServing * 100).rounded() / 100, "kcal": cost.kcalPerServing.rounded(),
                           "protein": cost.proteinPerServing.rounded()]
            accepted.append(c.raw)
            known.append(r)      // later candidates can't duplicate earlier ones
        } else {
            rejected.append(["title": title, "id": r.id, "reasons": rep.errors])
        }
    }
    let out: [String: Any] = ["accepted": accepted, "rejected": rejected, "stats": stats]
    let data = try JSONSerialization.data(withJSONObject: out, options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes])
    try data.write(to: args.path("out"))
    print("accepted \(accepted.count), rejected \(rejected.count)")
    for r in rejected { print("  ✗ \(r["title"] ?? "?"): \((r["reasons"] as? [String] ?? []).joined(separator: "; "))") }

case "lines":
    // Every ingredient line and what it matched, for auditing the matcher.
    let catalog = loadCatalog(args.path("catalog"))
    let file = loadRecipes(args.path("recipes"))
    for r in Library.recipes(file, catalog: catalog) {
        for line in r.ingredients { print("\(line.ingredientID ?? "—")\t\(line.text)\t\(r.id)") }
    }

case "explain":
    // Line-by-line amounts, cost and calories for one recipe.
    let catalog = loadCatalog(args.path("catalog"))
    let file = loadRecipes(args.path("recipes"))
    guard let id = args.options["id"], let a = file.recipes.first(where: { $0.id == id }) else { fail("--id not found") }
    let r = Library.recipes(Library.RecipeFile(version: 0, updated: "", recipes: [a]), catalog: catalog)[0]
    let costing = Costing(catalog: catalog, household: Household())
    for line in r.ingredients {
        let ing = line.ingredientID.flatMap { catalog[$0] }
        let base = catalog.baseAmount(line, scale: 1)
        let kcal = base.map { b in ing.map { $0.base == .g ? b / 100 * $0.kcal100 : b * $0.kcal100 } ?? 0 } ?? 0
        let cost = base.map { $0 * costing.unitPrice(line.ingredientID ?? "") } ?? 0
        print(String(format: "%-44@ → %-16@ %8.1f %@  $%5.2f  %5.0f kcal", line.text as NSString, (line.ingredientID ?? "—") as NSString,
                     base ?? 0, (ing?.base.rawValue ?? "") as NSString, cost, kcal))
    }
    let c = costing.cost(r)
    print(String(format: "per serving: $%.2f · %.0f kcal · %.0f g protein (serves %d)", c.perServing, c.kcalPerServing, c.proteinPerServing, r.servings))

default:
    fail("usage: pennycheck check|screen|explain --catalog C --recipes R [--candidates X --out O]")
}
