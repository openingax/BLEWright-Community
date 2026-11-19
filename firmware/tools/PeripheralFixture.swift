import AppKit
import CoreBluetooth

// Real BLE peripheral solely for exercising the S3 central. Never used by Mac RPC.
final class Fixture: NSObject, CBPeripheralManagerDelegate {
    var manager: CBPeripheralManager!
    var characteristic: CBMutableCharacteristic!
    var value = Data([66, 76, 69])
    var pending: Data?
    let label = NSTextField(labelWithString: "Starting Bluetooth…")
    var window: NSWindow!
    func start() {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 480, height: 180), styleMask: [.titled, .closable], backing: .buffered, defer: false)
        window.title = "BLEWright hardware fixture"
        label.frame = NSRect(x: 25, y: 50, width: 430, height: 100)
        label.maximumNumberOfLines = 5
        window.contentView?.addSubview(label)
        window.center(); window.makeKeyAndOrderFront(nil)
        manager = CBPeripheralManager(delegate: self, queue: .main)
    }
    func report(_ text: String) { print(text); fflush(stdout); label.stringValue = text }
    func peripheralManagerDidUpdateState(_ peripheral: CBPeripheralManager) {
        report("Bluetooth state: \(peripheral.state.rawValue)")
        guard peripheral.state == .poweredOn else { return }
        characteristic = CBMutableCharacteristic(type: CBUUID(string: "FFF1"), properties: [.read, .write, .writeWithoutResponse, .notify], value: nil, permissions: [.readable, .writeable])
        let service = CBMutableService(type: CBUUID(string: "FFF0"), primary: true)
        service.characteristics = [characteristic]
        peripheral.add(service)
    }
    func peripheralManager(_ peripheral: CBPeripheralManager, didAdd service: CBService, error: Error?) {
        guard error == nil else { report("ADD FAILED: \(error!)"); return }
        peripheral.startAdvertising([CBAdvertisementDataLocalNameKey: "BLEWright-HW", CBAdvertisementDataServiceUUIDsKey: [CBUUID(string: "FFF0")]])
    }
    func peripheralManagerDidStartAdvertising(_ peripheral: CBPeripheralManager, error: Error?) {
        report(error.map { "ADVERTISE FAILED: \($0)" } ?? "ADVERTISING BLEWright-HW / FFF0")
    }
    func peripheralManager(_ peripheral: CBPeripheralManager, didReceiveRead request: CBATTRequest) {
        guard request.offset <= value.count else { peripheral.respond(to: request, withResult: .invalidOffset); return }
        request.value = value.subdata(in: request.offset..<value.count)
        peripheral.respond(to: request, withResult: .success)
        report("READ \(value.map { String(format: "%02x", $0) }.joined())")
    }
    func peripheralManager(_ peripheral: CBPeripheralManager, didReceiveWrite requests: [CBATTRequest]) {
        guard let request = requests.first else { return }
        guard requests.allSatisfy({ $0.offset == 0 }) else { peripheral.respond(to: request, withResult: .invalidOffset); return }
        for request in requests { value = request.value ?? Data() }
        peripheral.respond(to: request, withResult: .success)
        report("WRITE \(value.map { String(format: "%02x", $0) }.joined())")
        if !peripheral.updateValue(value, for: characteristic, onSubscribedCentrals: nil) { pending = value }
    }
    func peripheralManager(_ peripheral: CBPeripheralManager, central: CBCentral, didSubscribeTo characteristic: CBCharacteristic) {
        report("SUBSCRIBED")
        if !peripheral.updateValue(value, for: self.characteristic, onSubscribedCentrals: [central]) { pending = value }
    }
    func peripheralManagerIsReady(toUpdateSubscribers peripheral: CBPeripheralManager) {
        if let pending, peripheral.updateValue(pending, for: characteristic, onSubscribedCentrals: nil) { self.pending = nil }
    }
}
let app = NSApplication.shared
app.setActivationPolicy(.regular)
let fixture = Fixture()
fixture.start()
app.activate(ignoringOtherApps: true)
app.run()
