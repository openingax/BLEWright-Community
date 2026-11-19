import CoreBluetooth
import SimulatorBLE
import UIKit

@main final class AppDelegate: UIResponder, UIApplicationDelegate {
  func application(
    _ application: UIApplication, configurationForConnecting session: UISceneSession,
    options: UIScene.ConnectionOptions
  ) -> UISceneConfiguration {
    let config = UISceneConfiguration(name: "Probe", sessionRole: session.role)
    config.delegateClass = ProbeSceneDelegate.self
    return config
  }
}
final class ProbeSceneDelegate: UIResponder, UIWindowSceneDelegate {
  var window: UIWindow?
  var probe: NativeProbe?
  func scene(
    _ scene: UIScene, willConnectTo session: UISceneSession, options: UIScene.ConnectionOptions
  ) {
    guard let scene = scene as? UIWindowScene else { return }
    let label = UILabel()
    label.numberOfLines = 0
    label.text = "BLEWright iOS Probe\nConnecting to Mac RPC…"
    label.textAlignment = .center
    let vc = UIViewController()
    vc.view.backgroundColor = .systemBackground
    label.frame = vc.view.bounds
    label.autoresizingMask = [.flexibleWidth, .flexibleHeight]
    vc.view.addSubview(label)
    window = UIWindow(windowScene: scene)
    window?.rootViewController = vc
    window?.makeKeyAndVisible()
    probe = NativeProbe { text in DispatchQueue.main.async { label.text = text } }
    probe?.start()
  }
}
// Deliberately uses ONLY CoreBluetooth APIs. The SimulatorBLE import above forces linking;
// the opt-in environment flag enables the hook before this standard central is constructed.
final class NativeProbe: NSObject, CBCentralManagerDelegate, CBPeripheralDelegate {
  let output: (String) -> Void
  var central: CBCentralManager!
  var peripheral: CBPeripheral?
  var characteristic: CBCharacteristic?
  let mode = ProcessInfo.processInfo.environment["BLEWRIGHT_PROBE_MODE"] ?? "normal"
  var stage = "starting"
  var finished = false
  var round = 0
  var receivedValue = false
  var queue: DispatchQueue = .main
  let queueKey = DispatchSpecificKey<Int>()
  let serviceUUID = CBUUID(string: "FFF0"), charUUID = CBUUID(string: "FFF1")
  let value = Data([1, 2, 3, 4]), withoutValue = Data([5, 6, 7])
  init(output: @escaping (String) -> Void) { self.output = output }
  func report(_ text: String) {
    output(text)
    NSLog("BLEWrightProbe: %@", text)
    let url = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
      .appendingPathComponent("probe-result.txt")
    try? text.write(to: url, atomically: true, encoding: .utf8)
  }
  func require(_ condition: Bool, _ message: String) -> Bool {
    if !condition { finish("FAIL: \(message)") }
    return condition
  }
  func finish(_ text: String) {
    guard !finished else { return }
    finished = true
    report(text)
  }
  func start() {
    queue.setSpecific(key: queueKey, value: round)
    if round == 0 {
      central = CBCentralManager(delegate: self, queue: nil)
    } else {
      central = CBCentralManager(delegate: self, queue: queue, options: [:])
    }
    DispatchQueue.main.asyncAfter(deadline: .now() + 15) { [weak self] in
      guard let s = self, !s.finished else { return }
      s.finish("FAIL: timeout at \(s.stage)")
    }
  }
  func checkQueue() -> Bool {
    require(DispatchQueue.getSpecific(key: queueKey) == round, "wrong callback queue")
  }
  func centralManagerDidUpdateState(_ central: CBCentralManager) {
    guard !finished, checkQueue() else { return }
    if central.state == .poweredOn && stage == "starting" {
      stage = "negativeScan"
      central.scanForPeripherals(withServices: [serviceUUID])
      central.stopScan()
      central.scanForPeripherals(withServices: [CBUUID(string: "EEEE")])
      queue.asyncAfter(deadline: .now() + 0.2) { [weak self] in
        guard let s = self, !s.finished else { return }
        central.stopScan()
        s.stage = "scan"
        central.scanForPeripherals(withServices: [s.serviceUUID])
      }
    } else if central.state == .poweredOff {
      if mode == "unavailable" {
        finish("PASS: CoreBluetooth reports poweredOff when RPC is unavailable")
      } else if mode != "loss" {
        finish("FAIL: RPC unavailable")
      }
    }
  }
  func centralManager(
    _ central: CBCentralManager, didDiscover peripheral: CBPeripheral,
    advertisementData: [String: Any], rssi RSSI: NSNumber
  ) {
    if mode == "loss" && stage == "waitingLoss" { return }
    guard !finished, checkQueue(), require(stage == "scan", "stopped/unmatched scan delivered"),
      require(peripheral.name == "BLEWright", "bad device name")
    else { return }
    self.peripheral = peripheral
    peripheral.delegate = self
    central.stopScan()
    stage = "connect"
    central.connect(peripheral)
  }
  func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
    guard !finished, checkQueue(), require(stage == "connect", "late connect"),
      require(
        peripheral === self.peripheral && peripheral.state == .connected,
        "peripheral identity/state")
    else { return }
    if mode == "loss" {
      stage = "waitingLoss"
      central.scanForPeripherals(withServices: [serviceUUID])
      report("CONNECTED_WAITING_FOR_SERVICE_LOSS")
      return
    }
    stage = "services"
    peripheral.discoverServices([serviceUUID])
  }
  func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
    guard !finished, checkQueue(),
      require(error == nil && peripheral.services?.count == 1, "service discovery")
    else { return }
    guard let service = peripheral.services?.first,
      require(service.uuid == serviceUUID && service.peripheral === peripheral, "service graph")
    else { return }
    stage = "characteristics"
    peripheral.discoverCharacteristics([charUUID], for: service)
  }
  func peripheral(
    _ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?
  ) {
    guard !finished, checkQueue(),
      require(error == nil && service.characteristics?.count == 1, "characteristic discovery"),
      let c = service.characteristics?.first,
      require(c.service === service && c.uuid == charUUID, "characteristic graph")
    else { return }
    characteristic = c
    stage = "descriptors"
    peripheral.discoverDescriptors(for: c)
  }
  func peripheral(
    _ peripheral: CBPeripheral, didDiscoverDescriptorsFor characteristic: CBCharacteristic,
    error: Error?
  ) {
    guard !finished, checkQueue(),
      require(
        error == nil && characteristic.descriptors?.first?.characteristic === characteristic,
        "descriptor graph")
    else { return }
    let limit = peripheral.maximumWriteValueLength(for: .withResponse)
    guard require(limit == 244, "expected mock ATT MTU 247 (payload 244), got \(limit)")
    else { return }
    stage = "oversize"
    peripheral.writeValue(Data(repeating: 9, count: limit + 1), for: characteristic, type: .withResponse)
  }
  func peripheral(
    _ peripheral: CBPeripheral, didWriteValueFor characteristic: CBCharacteristic, error: Error?
  ) {
    if stage == "oversize" {
      guard require(error != nil, "oversize accepted") else { return }
      stage = "write"
      peripheral.writeValue(value, for: characteristic, type: .withResponse)
      return
    }
    if stage == "quietWrite" {
      guard require(error == nil, "write after unsubscribe") else { return }
      queue.asyncAfter(deadline: .now() + 0.1) {
        self.stage = "disconnect"
        self.central.cancelPeripheralConnection(peripheral)
        self.central.cancelPeripheralConnection(peripheral)
      }
      return
    }
    guard !finished, checkQueue(),
      require(stage == "write", "unexpected write callback (withoutResponse?)"),
      require(error == nil, "write failed")
    else { return }
    stage = "read"
    peripheral.readValue(for: characteristic)
  }
  func peripheral(
    _ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic, error: Error?
  ) {
    guard !finished, checkQueue(),
      require(error == nil && characteristic === self.characteristic, "value error/identity")
    else { return }
    if stage == "read" {
      guard require(characteristic.value == value, "read roundtrip") else { return }
      stage = "subscribe"
      peripheral.setNotifyValue(true, for: characteristic)
    } else if stage == "notification" {
      guard require(characteristic.isNotifying && characteristic.value == value, "initial notify")
      else { return }
      stage = "withoutResponse"
      peripheral.writeValue(withoutValue, for: characteristic, type: .withoutResponse)
    } else if stage == "withoutResponse" {
      guard require(characteristic.value == withoutValue, "withoutResponse notify") else { return }
      stage = "unsubscribe"
      peripheral.setNotifyValue(false, for: characteristic)
    } else {
      finish("FAIL: unexpected value at \(stage)")
    }
  }
  func peripheral(
    _ peripheral: CBPeripheral, didUpdateNotificationStateFor characteristic: CBCharacteristic,
    error: Error?
  ) {
    guard !finished, checkQueue(), require(error == nil, "notify configuration") else { return }
    if stage == "subscribe" {
      guard require(characteristic.isNotifying, "isNotifying false") else { return }
      stage = "notification"
    } else if stage == "unsubscribe" {
      guard require(!characteristic.isNotifying, "unsubscribe flag") else { return }
      stage = "quietWrite"
      peripheral.writeValue(Data([8]), for: characteristic, type: .withResponse)
    } else {
      finish("FAIL: unexpected subscription callback")
    }
  }
  func peripheralIsReady(toSendWriteWithoutResponse peripheral: CBPeripheral) {
    _ = require(peripheral.canSendWriteWithoutResponse, "write readiness")
  }
  func centralManager(
    _ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?
  ) { finish("FAIL: connect \(String(describing:error))") }
  func centralManager(
    _ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral, error: Error?
  ) {
    if mode == "loss" {
      guard
        require(
          error != nil && peripheral.state == .disconnected && central.state == .poweredOff
            && !central.isScanning, "service loss state")
      else { return }
      finish("PASS: RPC loss disconnects peripheral, stops scanning and marks central poweredOff")
      return
    }
    guard !finished, checkQueue(),
      require(error == nil && peripheral.state == .disconnected, "disconnect failed")
    else { return }
    if stage == "disconnect" {
      stage = "cancel"
      central.connect(peripheral)
      central.cancelPeripheralConnection(peripheral)
    } else if stage == "cancel" {
      if round == 0 {
        report("ROUND_PASS main queue")
        round = 1
        queue = DispatchQueue(label: "space.nomoloop.blewright.probe")
        stage = "starting"
        start()
      } else {
        queue.asyncAfter(deadline: .now() + 0.15) {
          self.finish(
            "PASS: CoreBluetooth scan/filter/stop, connect/cancel, service graph, write/read/oversize, notify/unsubscribe, withoutResponse, main/custom delegate queues"
          )
        }
      }
    } else {
      finish("FAIL: duplicate/early disconnect at \(stage)")
    }
  }
}
