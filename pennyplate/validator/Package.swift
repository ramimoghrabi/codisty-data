// swift-tools-version: 6.0
// Checks Pennyplate recipes with the app's own parser, matcher and costing.
// Sources/PennyCore holds the parsing and costing files from Pennyplate's PennyCore
// (refresh it with Pennyplate/Tools/sync-data-repo.sh when the app changes).
import PackageDescription

let package = Package(
    name: "pennycheck",
    platforms: [.macOS(.v14)],
    targets: [
        .target(name: "PennyCore"),
        .executableTarget(name: "pennycheck", dependencies: ["PennyCore"]),
    ],
    swiftLanguageModes: [.v5]
)
