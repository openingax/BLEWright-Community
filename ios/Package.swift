// swift-tools-version: 5.9
import PackageDescription

let package = Package(
  name: "SimulatorBLE",
  platforms: [.iOS(.v15)],
  products: [.library(name: "SimulatorBLE", targets: ["SimulatorBLE"])],
  targets: [
    .target(
      name: "SimulatorBLE", path: "Sources/SimulatorBLE", publicHeadersPath: "include",
      cSettings: [.define("DEBUG", .when(configuration: .debug))],
      linkerSettings: [.linkedFramework("CoreBluetooth"), .linkedFramework("Network")])
  ]
)
