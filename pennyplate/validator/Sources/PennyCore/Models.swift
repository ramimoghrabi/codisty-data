import Foundation

// MARK: - Catalog

/// Where things live in a store — the grocery list is sorted this way.
public enum Aisle: String, Codable, CaseIterable, Sendable {
    case produce, meat, seafood, dairy, bakery, pantry, canned, spices, international, frozen, other
}

/// A size it's sold in, at the national average price.
public struct Package: Codable, Hashable, Sendable {
    public var amount: Double       // in the ingredient's base unit
    public var price: Double        // USD, national average
    public var label: String        // "1 lb bag", "dozen", "15 oz can"

    public init(amount: Double, price: Double, label: String) {
        self.amount = amount
        self.price = price
        self.label = label
    }
}

/// One thing you can buy. Prices are national averages (BLS where it
/// publishes one, careful estimates otherwise), adjusted later for the
/// user's region and kind of store.
public struct Ingredient: Codable, Identifiable, Hashable, Sendable {
    public var id: String
    public var name: String
    public var aliases: [String]
    public var aisle: Aisle
    public var base: BaseUnit
    /// Grams in one cup, for volume measures of things bought by weight.
    public var gramsPerCup: Double?
    /// Grams in one piece (an onion, a clove), for counts of things bought by weight.
    public var gramsEach: Double?
    public var packages: [Package]
    public var kcal100: Double       // per 100 g, or per piece for `each`
    public var protein100: Double
    /// Salt, oil, spices: assumed to be at home unless the user says otherwise.
    public var staple: Bool
    /// How long it keeps once bought (days), for the pantry.
    public var keepsDays: Int
    /// "bls" when the price comes from BLS average prices, "est" otherwise.
    public var priceSource: String

    public init(id: String, name: String, aliases: [String], aisle: Aisle, base: BaseUnit, gramsPerCup: Double?, gramsEach: Double?,
                packages: [Package], kcal100: Double, protein100: Double, staple: Bool, keepsDays: Int, priceSource: String) {
        self.id = id
        self.name = name
        self.aliases = aliases
        self.aisle = aisle
        self.base = base
        self.gramsPerCup = gramsPerCup
        self.gramsEach = gramsEach
        self.packages = packages
        self.kcal100 = kcal100
        self.protein100 = protein100
        self.staple = staple
        self.keepsDays = keepsDays
        self.priceSource = priceSource
    }

    /// The cheapest price per base unit across the sizes it's sold in.
    public var unitPrice: Double {
        packages.map { $0.price / max($0.amount, 0.0001) }.min() ?? 0
    }
}

// MARK: - Recipes

public enum Cuisine: String, Codable, CaseIterable, Sendable {
    case american, mexican, italian, asian, indian, middleEastern, mediterranean, breakfast
}

public enum Diet: String, Codable, CaseIterable, Sendable {
    case vegetarian, vegan, glutenFree, dairyFree, highProtein, pescatarian
}

public enum Equipment: String, Codable, CaseIterable, Sendable {
    case oven, stovetop, slowCooker, airFryer, pressureCooker, microwave, blender
}

public enum MealType: String, Codable, CaseIterable, Sendable { case breakfast, lunch, dinner }

/// One line of a recipe, as written and as understood.
public struct RecipeIngredient: Codable, Hashable, Sendable {
    public var text: String
    public var amount: Double?
    public var unit: Unit?
    public var name: String
    public var note: String
    public var ingredientID: String?

    public init(text: String, amount: Double? = nil, unit: Unit? = nil, name: String, note: String = "", ingredientID: String? = nil) {
        self.text = text
        self.amount = amount
        self.unit = unit
        self.name = name
        self.note = note
        self.ingredientID = ingredientID
    }
}

public struct RecipeSource: Codable, Hashable, Sendable {
    public enum Kind: String, Codable, Sendable { case builtIn, web, tiktok, instagram, youtube, pinterest, text, scan, manual }
    public var kind: Kind
    public var url: String?
    public var site: String?
    public var author: String?
    /// File name of a downloaded photo in the app's images folder.
    public var imageFile: String?

    public init(kind: Kind, url: String? = nil, site: String? = nil, author: String? = nil, imageFile: String? = nil) {
        self.kind = kind
        self.url = url
        self.site = site
        self.author = author
        self.imageFile = imageFile
    }
}

public struct Recipe: Codable, Identifiable, Hashable, Sendable {
    public var id: String
    public var title: String
    public var summary: String
    public var cuisine: Cuisine
    public var diets: [Diet]
    public var meal: MealType
    public var servings: Int
    public var minutes: Int
    public var equipment: [Equipment]
    public var ingredients: [RecipeIngredient]
    public var steps: [String]
    /// The plate art: a dish emoji and a table colour.
    public var emoji: String
    public var tint: String
    /// Days it keeps in the fridge — good for leftovers when ≥ 2.
    public var keepsDays: Int
    public var source: RecipeSource
    public var tags: [String]
    public var createdAt: Date

    public init(id: String = UUID().uuidString, title: String, summary: String = "", cuisine: Cuisine = .american, diets: [Diet] = [],
                meal: MealType = .dinner, servings: Int = 4, minutes: Int = 30, equipment: [Equipment] = [.stovetop],
                ingredients: [RecipeIngredient], steps: [String], emoji: String = "🍽️", tint: String = "amber", keepsDays: Int = 3,
                source: RecipeSource = RecipeSource(kind: .manual), tags: [String] = [], createdAt: Date = Date()) {
        self.id = id
        self.title = title
        self.summary = summary
        self.cuisine = cuisine
        self.diets = diets
        self.meal = meal
        self.servings = servings
        self.minutes = minutes
        self.equipment = equipment
        self.ingredients = ingredients
        self.steps = steps
        self.emoji = emoji
        self.tint = tint
        self.keepsDays = keepsDays
        self.source = source
        self.tags = tags
        self.createdAt = createdAt
    }

    public var isImported: Bool { source.kind != .builtIn }
}

// MARK: - Household & plan

/// Discount stores run cheaper than the national average, premium ones dearer.
public enum StoreTier: String, Codable, CaseIterable, Sendable {
    case discount, standard, premium
    public var multiplier: Double {
        switch self {
        case .discount: return 0.86
        case .standard: return 1.0
        case .premium: return 1.28
        }
    }
}

/// BLS regions (2025–26 averages relative to the US city average).
public enum Region: String, Codable, CaseIterable, Sendable {
    case national, northeast, midwest, south, west
    public var multiplier: Double {
        switch self {
        case .national: return 1.0
        case .northeast: return 1.013
        case .midwest: return 1.013
        case .south: return 0.982
        case .west: return 1.04
        }
    }
}

public struct Household: Codable, Hashable, Sendable {
    public var people: Int = 2
    public var weeklyBudget: Double = 75
    public var dinnersPerWeek: Int = 5
    public var lunchLeftovers = true
    public var diets: [Diet] = []
    public var avoid: [String] = []          // ingredient ids
    public var cuisines: [Cuisine] = Cuisine.allCases
    public var equipment: [Equipment] = [.oven, .stovetop, .microwave]
    public var maxMinutes: Int = 60
    public var store: StoreTier = .standard
    public var region: Region = .national
    public var currency: String = "USD"
    /// Converts USD national prices into the user's currency and price level.
    public var priceFactor: Double = 1

    public init() {}

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let d = Household()
        people = (try? c.decodeIfPresent(Int.self, forKey: .people)) ?? d.people
        weeklyBudget = (try? c.decodeIfPresent(Double.self, forKey: .weeklyBudget)) ?? d.weeklyBudget
        dinnersPerWeek = (try? c.decodeIfPresent(Int.self, forKey: .dinnersPerWeek)) ?? d.dinnersPerWeek
        lunchLeftovers = (try? c.decodeIfPresent(Bool.self, forKey: .lunchLeftovers)) ?? d.lunchLeftovers
        diets = (try? c.decodeIfPresent([Diet].self, forKey: .diets)) ?? []
        avoid = (try? c.decodeIfPresent([String].self, forKey: .avoid)) ?? []
        cuisines = (try? c.decodeIfPresent([Cuisine].self, forKey: .cuisines)) ?? d.cuisines
        equipment = (try? c.decodeIfPresent([Equipment].self, forKey: .equipment)) ?? d.equipment
        maxMinutes = (try? c.decodeIfPresent(Int.self, forKey: .maxMinutes)) ?? d.maxMinutes
        store = (try? c.decodeIfPresent(StoreTier.self, forKey: .store)) ?? d.store
        region = (try? c.decodeIfPresent(Region.self, forKey: .region)) ?? d.region
        currency = (try? c.decodeIfPresent(String.self, forKey: .currency)) ?? d.currency
        priceFactor = (try? c.decodeIfPresent(Double.self, forKey: .priceFactor)) ?? d.priceFactor
    }

    /// Everything that turns a national USD price into this household's.
    public var multiplier: Double { store.multiplier * region.multiplier * priceFactor }
}

public struct PlannedMeal: Codable, Hashable, Identifiable, Sendable {
    public var id: UUID
    public var day: String           // Day.key
    public var meal: MealType
    public var recipeID: String
    public var servings: Int
    /// Eaten from an earlier cook's extra portions — nothing to buy.
    public var leftoverOf: UUID?
    public var cooked: Bool

    public init(id: UUID = UUID(), day: String, meal: MealType, recipeID: String, servings: Int, leftoverOf: UUID? = nil, cooked: Bool = false) {
        self.id = id
        self.day = day
        self.meal = meal
        self.recipeID = recipeID
        self.servings = servings
        self.leftoverOf = leftoverOf
        self.cooked = cooked
    }
}

/// Something at home: a staple, or what's left of a package.
public struct PantryItem: Codable, Hashable, Identifiable, Sendable {
    public var id: String { ingredientID }
    public var ingredientID: String
    /// Amount in the ingredient's base unit; nil means "plenty" (a staple).
    public var amount: Double?
    public var added: Date

    public init(ingredientID: String, amount: Double?, added: Date = Date()) {
        self.ingredientID = ingredientID
        self.amount = amount
        self.added = added
    }
}

/// A line on the shopping list.
public struct GroceryLine: Codable, Hashable, Identifiable, Sendable {
    public var id: String
    public var ingredientID: String?
    public var name: String
    public var aisle: Aisle
    /// What the recipes need, in base units.
    public var need: Double
    /// What to buy: package labels with counts.
    public var buy: [String]
    /// Amount bought in base units (≥ need).
    public var bought: Double
    public var cost: Double
    public var forRecipes: [String]
    public var custom: Bool

    public init(id: String, ingredientID: String?, name: String, aisle: Aisle, need: Double, buy: [String], bought: Double,
                cost: Double, forRecipes: [String], custom: Bool = false) {
        self.id = id
        self.ingredientID = ingredientID
        self.name = name
        self.aisle = aisle
        self.need = need
        self.buy = buy
        self.bought = bought
        self.cost = cost
        self.forRecipes = forRecipes
        self.custom = custom
    }
}

public enum Day {
    public static func key(_ date: Date, calendar: Calendar = .current) -> String {
        let c = calendar.dateComponents([.year, .month, .day], from: date)
        return String(format: "%04d-%02d-%02d", c.year ?? 0, c.month ?? 0, c.day ?? 0)
    }
    public static func date(_ key: String, calendar: Calendar = .current) -> Date? {
        let p = key.split(separator: "-").compactMap { Int($0) }
        guard p.count == 3 else { return nil }
        return calendar.date(from: DateComponents(year: p[0], month: p[1], day: p[2]))
    }
    /// Monday of the week containing `date`.
    public static func weekStart(_ date: Date, calendar: Calendar = .current) -> Date {
        var cal = calendar
        cal.firstWeekday = 2
        return cal.dateInterval(of: .weekOfYear, for: date)?.start ?? cal.startOfDay(for: date)
    }
}
