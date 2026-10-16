import Foundation

/// The catalog and recipe files: bundled in the app, refreshed from
/// data.codisty.com when a newer version is published (new recipes weekly,
/// prices monthly).
public enum Library {
    public struct CatalogFile: Codable, Sendable {
        public var version: Int
        public var updated: String
        public var items: [Ingredient]

        public init(version: Int, updated: String, items: [Ingredient]) {
            self.version = version
            self.updated = updated
            self.items = items
        }
    }

    /// Recipes as authored: ingredient lines are plain text and get parsed
    /// and matched on load, so the files stay readable and easy to extend.
    public struct RecipeFile: Codable, Sendable {
        public var version: Int
        public var updated: String
        public var recipes: [Authored]

        public init(version: Int, updated: String, recipes: [Authored]) {
            self.version = version
            self.updated = updated
            self.recipes = recipes
        }
    }

    public struct Authored: Codable, Sendable {
        public var id: String
        public var title: String
        public var summary: String
        public var cuisine: Cuisine
        public var diets: [Diet]
        public var meal: MealType
        public var servings: Int
        public var minutes: Int
        public var equipment: [Equipment]
        public var emoji: String
        public var tint: String
        public var keepsDays: Int
        public var tags: [String]
        public var ingredients: [String]
        public var steps: [String]
        /// "yyyy-MM-dd" the recipe was published; nil for the launch set.
        public var added: String?
        public var photo: Photo?

        public init(id: String, title: String, summary: String, cuisine: Cuisine, diets: [Diet], meal: MealType, servings: Int,
                    minutes: Int, equipment: [Equipment], emoji: String, tint: String, keepsDays: Int, tags: [String],
                    ingredients: [String], steps: [String], added: String? = nil, photo: Photo? = nil) {
            self.id = id
            self.title = title
            self.summary = summary
            self.cuisine = cuisine
            self.diets = diets
            self.meal = meal
            self.servings = servings
            self.minutes = minutes
            self.equipment = equipment
            self.emoji = emoji
            self.tint = tint
            self.keepsDays = keepsDays
            self.tags = tags
            self.ingredients = ingredients
            self.steps = steps
            self.added = added
            self.photo = photo
        }

        /// When it was published, at noon UTC so it's the same day everywhere.
        public var addedDate: Date {
            guard let added, let d = Library.day.date(from: added) else { return Date(timeIntervalSince1970: 0) }
            return d.addingTimeInterval(12 * 3600)
        }
    }

    static let day: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone(identifier: "UTC")
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()

    /// Prices outside the US: exchange rates and how food prices compare
    /// with the US, refreshed weekly.
    public struct WorldFile: Codable, Sendable {
        public var version: Int
        public var updated: String
        /// Currency units per US dollar.
        public var rates: [String: Double]
        /// Food price level vs the US by country (ISO alpha-2); 0.93 = 7% cheaper.
        public var levels: [String: Double]

        public init(version: Int = 0, updated: String = "", rates: [String: Double] = [:], levels: [String: Double] = [:]) {
            self.version = version
            self.updated = updated
            self.rates = rates
            self.levels = levels
        }

        /// What one US dollar of groceries costs in `country`, in `currency`;
        /// nil when there's no rate for the currency.
        public func factor(country: String, currency: String) -> Double? {
            let level = country == "US" ? 1 : levels[country] ?? 1
            guard let rate = currency == "USD" ? 1 : rates[currency] else { return nil }
            return level * rate
        }
    }

    public static func world(_ data: Data) throws -> WorldFile {
        try JSONDecoder().decode(WorldFile.self, from: data)
    }

    /// Recipes published in the last `days` days count as new.
    public static func isNew(_ r: Recipe, now: Date = Date(), days: Double = 10) -> Bool {
        r.source.kind == .builtIn && r.createdAt.timeIntervalSince1970 > 0 && now.timeIntervalSince(r.createdAt) < days * 86_400
    }

    public static func catalog(_ data: Data) throws -> CatalogFile {
        try JSONDecoder().decode(CatalogFile.self, from: data)
    }

    public static func recipeFile(_ data: Data) throws -> RecipeFile {
        try JSONDecoder().decode(RecipeFile.self, from: data)
    }

    public static func recipes(_ file: RecipeFile, catalog: Catalog) -> [Recipe] {
        file.recipes.map { a in
            catalog.resolve(Recipe(id: a.id, title: a.title, summary: a.summary, cuisine: a.cuisine, diets: a.diets, meal: a.meal,
                                   servings: a.servings, minutes: a.minutes, equipment: a.equipment,
                                   ingredients: a.ingredients.map(IngredientParser.parse), steps: a.steps, emoji: a.emoji, tint: a.tint,
                                   keepsDays: a.keepsDays, source: RecipeSource(kind: .builtIn), tags: a.tags,
                                   createdAt: a.addedDate, photo: a.photo))
        }
    }
}
