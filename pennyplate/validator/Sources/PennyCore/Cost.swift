import Foundation

/// What a recipe costs and gives, honestly: the cost of what's *eaten*
/// (a share of each package) is kept apart from what you *pay at the till*
/// (whole packages), so one egg is never priced as a dozen — and never
/// priced as free either.
public struct Costing: Sendable {
    public let catalog: Catalog
    public let household: Household
    /// What the user says things cost where they shop, per base unit.
    public let priceBook: [String: Double]

    public init(catalog: Catalog, household: Household, priceBook: [String: Double] = [:]) {
        self.catalog = catalog
        self.household = household
        self.priceBook = priceBook
    }

    /// Price per base unit for this household.
    public func unitPrice(_ id: String) -> Double {
        if let own = priceBook[id] { return own }
        return (catalog[id]?.unitPrice ?? 0) * household.multiplier
    }

    /// Price of one package for this household.
    public func packagePrice(_ id: String, _ p: Package) -> Double {
        if let own = priceBook[id] { return own * p.amount }
        return p.price * household.multiplier
    }

    public struct Breakdown: Sendable {
        public var total: Double
        public var perServing: Double
        public var lines: [(index: Int, cost: Double)]
        public var unpriced: Int
        public var kcalPerServing: Double
        public var proteinPerServing: Double
    }

    /// Cost of the portions used, for `servings` people.
    public func cost(_ r: Recipe, servings: Int? = nil) -> Breakdown {
        let s = Double(servings ?? r.servings)
        let scale = s / Double(max(r.servings, 1))
        var total = 0.0, kcal = 0.0, protein = 0.0
        var lines: [(Int, Double)] = []
        var unpriced = 0
        for (i, line) in r.ingredients.enumerated() {
            guard let id = line.ingredientID, let ing = catalog[id] else {
                if line.amount != nil { unpriced += 1 }
                continue
            }
            guard let base = catalog.baseAmount(line, scale: scale) else {
                // "Salt to taste": a pinch of a staple.
                continue
            }
            let c = base * unitPrice(id)
            total += c
            lines.append((i, c))
            if ing.base == .g {
                kcal += base / 100 * ing.kcal100
                protein += base / 100 * ing.protein100
            } else {
                kcal += base * ing.kcal100
                protein += base * ing.protein100
            }
        }
        return Breakdown(total: total, perServing: total / max(s, 1), lines: lines, unpriced: unpriced,
                         kcalPerServing: kcal / max(s, 1), proteinPerServing: protein / max(s, 1))
    }

    // MARK: - Shopping

    /// Cheapest set of packages covering `need` base units.
    public func packages(for id: String, need: Double) -> (labels: [String], amount: Double, cost: Double) {
        guard let ing = catalog[id], !ing.packages.isEmpty, need > 0 else { return ([], 0, 0) }
        let sizes = ing.packages.sorted { $0.amount < $1.amount }
        var best: (cost: Double, counts: [Int])?
        // Small search: up to 12 of each size, at most three sizes deep.
        func search(_ i: Int, _ have: Double, _ cost: Double, _ counts: [Int]) {
            if have >= need - 0.0001 {
                if best == nil || cost < best!.cost - 0.0001 { best = (cost, counts) }
                return
            }
            guard i < sizes.count else { return }
            if let b = best, cost >= b.cost { return }
            let p = sizes[i]
            let maxCount = min(12, Int(ceil((need - have) / p.amount)))
            for n in stride(from: maxCount, through: 0, by: -1) {
                var c = counts
                c[i] = n
                search(i + 1, have + Double(n) * p.amount, cost + Double(n) * packagePrice(id, p), c)
            }
        }
        search(0, 0, 0, Array(repeating: 0, count: sizes.count))
        guard let b = best else {
            // Bigger than a dozen of the largest size: buy by weight.
            let p = sizes.last!
            let n = Int(ceil(need / p.amount))
            return (["\(n) × \(p.label)"], Double(n) * p.amount, Double(n) * packagePrice(id, p))
        }
        var labels: [String] = []
        var amount = 0.0
        for (i, n) in b.counts.enumerated() where n > 0 {
            labels.append(Costing.label(sizes[i].label, count: n))
            amount += Double(n) * sizes[i].amount
        }
        return (labels, amount, b.cost)
    }

    /// "1 cucumber" × 4 → "4 cucumbers"; "15 oz can" × 2 → "2 × 15 oz can".
    public static func label(_ label: String, count n: Int) -> String {
        guard n > 1 else { return label }
        if label.hasPrefix("1 "), !label.dropFirst(2).contains(" "), !label.contains("(") {
            let noun = String(label.dropFirst(2))
            let plural: String
            if ["s", "x", "z"].contains(noun.suffix(1)) || noun.hasSuffix("ch") || noun.hasSuffix("sh") { plural = noun + "es" }
            else { plural = noun + "s" }
            return "\(n) \(plural)"
        }
        return "\(n) × \(label)"
    }

    public struct Shop: Sendable {
        public var lines: [GroceryLine]
        /// Paid at the till.
        public var total: Double
        /// The share of that eaten this week.
        public var used: Double
        /// What stays in the pantry afterwards, by ingredient (base units).
        public var leftover: [String: Double]
        /// Lines the catalog didn't recognise (bought as written).
        public var unknown: [GroceryLine]
        /// Everything the meals need, by ingredient (base units).
        public var needs: [String: Double] = [:]

        public init(lines: [GroceryLine], total: Double, used: Double, leftover: [String: Double], unknown: [GroceryLine], needs: [String: Double] = [:]) {
            self.lines = lines
            self.total = total
            self.used = used
            self.leftover = leftover
            self.unknown = unknown
            self.needs = needs
        }

        /// The pantry after shopping and cooking all of it: what was at home
        /// plus what was bought, minus what the meals use.
        public func pantryAfter(_ pantry: [PantryItem], now: Date = Date()) -> [PantryItem] {
            var out: [String: PantryItem] = [:]
            for p in pantry { out[p.ingredientID] = p }
            for (id, need) in needs {
                if let p = out[id], p.amount == nil { continue }          // a staple: still "plenty"
                let have = out[id]?.amount ?? 0
                let bought = lines.first { $0.ingredientID == id }?.bought ?? 0
                let rest = have + bought - need
                if rest > 0.0001 { out[id] = PantryItem(ingredientID: id, amount: rest, added: now) } else { out[id] = nil }
            }
            return out.values.sorted { $0.ingredientID < $1.ingredientID }
        }
    }

    /// The shopping list for a set of planned meals, after what's at home.
    public func shop(_ meals: [(recipe: Recipe, servings: Int)], pantry: [PantryItem]) -> Shop {
        var need: [String: Double] = [:]
        var forRecipes: [String: [String]] = [:]
        var unknown: [String: GroceryLine] = [:]
        var used = 0.0
        for (r, s) in meals {
            let scale = Double(s) / Double(max(r.servings, 1))
            for line in r.ingredients {
                guard let id = line.ingredientID, catalog[id] != nil else {
                    let key = Catalog.normalize(line.name)
                    guard !key.isEmpty else { continue }
                    var g = unknown[key] ?? GroceryLine(id: "x-" + key, ingredientID: nil, name: line.name.capitalizedFirst, aisle: .other,
                                                        need: 0, buy: [], bought: 0, cost: 0, forRecipes: [])
                    if !g.forRecipes.contains(r.title) { g.forRecipes.append(r.title) }
                    if let a = line.amount {
                        g.buy.append([Fraction.pretty(a * scale), line.unit?.label ?? ""].filter { !$0.isEmpty }.joined(separator: " "))
                    }
                    unknown[key] = g
                    continue
                }
                let amount = catalog.baseAmount(line, scale: scale) ?? 0
                need[id, default: 0] += amount
                used += amount * unitPrice(id)
                if !(forRecipes[id]?.contains(r.title) ?? false) { forRecipes[id, default: []].append(r.title) }
            }
        }
        var lines: [GroceryLine] = []
        var leftover: [String: Double] = [:]
        var total = 0.0
        let have = Dictionary(pantry.map { ($0.ingredientID, $0.amount) }, uniquingKeysWith: { a, b in
            guard let a, let b else { return nil }
            return a + b
        })
        for (id, amount) in need {
            guard let ing = catalog[id] else { continue }
            // A staple at home ("plenty") or a staple used in tiny amounts.
            if let h = have[id] {
                guard let h else { continue }
                let rest = amount - h
                if rest <= 0.0001 { continue }
                let p = packages(for: id, need: rest)
                lines.append(GroceryLine(id: id, ingredientID: id, name: ing.name, aisle: ing.aisle, need: rest, buy: p.labels,
                                         bought: p.amount, cost: p.cost, forRecipes: forRecipes[id] ?? []))
                total += p.cost
                leftover[id] = p.amount - rest
                continue
            }
            if amount <= 0, !ing.staple {
                // Listed without an amount ("cilantro, for serving"): one of the smallest pack.
                let p = packages(for: id, need: ing.packages.map(\.amount).min() ?? 1)
                lines.append(GroceryLine(id: id, ingredientID: id, name: ing.name, aisle: ing.aisle, need: 0, buy: p.labels,
                                         bought: p.amount, cost: p.cost, forRecipes: forRecipes[id] ?? []))
                total += p.cost
                leftover[id] = p.amount
                continue
            }
            if amount <= 0 { continue }
            let p = packages(for: id, need: amount)
            lines.append(GroceryLine(id: id, ingredientID: id, name: ing.name, aisle: ing.aisle, need: amount, buy: p.labels,
                                     bought: p.amount, cost: p.cost, forRecipes: forRecipes[id] ?? []))
            total += p.cost
            leftover[id] = max(0, p.amount - amount)
        }
        let order = Aisle.allCases
        lines.sort {
            let a = order.firstIndex(of: $0.aisle)!, b = order.firstIndex(of: $1.aisle)!
            return a != b ? a < b : $0.name < $1.name
        }
        let unk = unknown.values.sorted { $0.name < $1.name }
        return Shop(lines: lines, total: total, used: used, leftover: leftover.filter { $0.value > 0.0001 }, unknown: unk, needs: need)
    }
}

extension String {
    public var capitalizedFirst: String { prefix(1).uppercased() + dropFirst() }
}
