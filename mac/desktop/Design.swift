import AppKit

enum WorkbenchStyle {
    static let ink = NSColor(srgbRed: 0.07, green: 0.13, blue: 0.22, alpha: 1)
    static let mint = NSColor(srgbRed: 0.36, green: 0.91, blue: 0.76, alpha: 1)
    static let accent = NSColor(srgbRed: 0.02, green: 0.46, blue: 0.39, alpha: 1)
    static let background = NSColor(name: nil) { $0.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua ? NSColor(srgbRed: 0.10, green: 0.12, blue: 0.15, alpha: 1) : NSColor(srgbRed: 0.95, green: 0.96, blue: 0.97, alpha: 1) }
    static func text(_ value: String, size: CGFloat = 13, weight: NSFont.Weight = .regular, color: NSColor = .labelColor) -> NSTextField {
        let field = NSTextField(labelWithString: value)
        field.font = .systemFont(ofSize: size, weight: weight); field.textColor = color
        return field
    }
    static func symbol(_ name: String, size: CGFloat = 18, color: NSColor = .secondaryLabelColor) -> NSImageView {
        let view = NSImageView()
        view.image = NSImage(systemSymbolName: name, accessibilityDescription: nil)?.withSymbolConfiguration(.init(pointSize: size, weight: .medium))
        view.contentTintColor = color
        return view
    }
    static func stack(_ views: [NSView], vertical: Bool = false, spacing: CGFloat = 8) -> NSStackView {
        let stack = NSStackView(views: views); stack.orientation = vertical ? .vertical : .horizontal
        stack.alignment = vertical ? .leading : .centerY; stack.spacing = spacing
        return stack
    }
    static func pin(_ child: NSView, in parent: NSView, inset: CGFloat = 0) {
        parent.addSubview(child); child.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([child.leadingAnchor.constraint(equalTo: parent.leadingAnchor, constant: inset), child.trailingAnchor.constraint(equalTo: parent.trailingAnchor, constant: -inset), child.topAnchor.constraint(equalTo: parent.topAnchor, constant: inset), child.bottomAnchor.constraint(equalTo: parent.bottomAnchor, constant: -inset)])
    }
}

final class WorkbenchPanel: NSView {
    let fill: NSColor
    let radius: CGFloat
    init(_ fill: NSColor = .controlBackgroundColor, radius: CGFloat = 18) { self.fill = fill; self.radius = radius; super.init(frame: .zero) }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
    override func draw(_ dirtyRect: NSRect) { fill.setFill(); NSBezierPath(roundedRect: bounds, xRadius: radius, yRadius: radius).fill() }
}

/// Resolution-independent companion to the app icon; purely decorative, never a service indicator.
final class WorkstationArtwork: NSView {
    override var isFlipped: Bool { true }
    override func draw(_ dirtyRect: NSRect) {
        let scale = min(bounds.width / 240, bounds.height / 160)
        let transform = NSAffineTransform(); transform.translateX(by: (bounds.width - 240 * scale) / 2, yBy: (bounds.height - 160 * scale) / 2); transform.scale(by: scale); transform.concat()
        for radius: CGFloat in [44, 65, 86] {
            WorkbenchStyle.mint.withAlphaComponent(0.10).setStroke()
            let orbit = NSBezierPath(ovalIn: NSRect(x: 120-radius, y: 80-radius, width: radius*2, height: radius*2)); orbit.lineWidth = 1; orbit.stroke()
        }
        let cable = NSBezierPath(); cable.move(to: NSPoint(x: 120, y: 122)); cable.line(to: NSPoint(x: 120, y: 141)); cable.curve(to: NSPoint(x: 225, y: 154), controlPoint1: NSPoint(x: 120, y: 169), controlPoint2: NSPoint(x: 190, y: 143)); cable.lineWidth = 4; WorkbenchStyle.mint.withAlphaComponent(0.32).setStroke(); cable.stroke()
        let board = NSRect(x: 73, y: 24, width: 94, height: 104)
        NSColor(srgbRed: 0.13, green: 0.27, blue: 0.32, alpha: 1).setFill(); NSBezierPath(roundedRect: board, xRadius: 16, yRadius: 16).fill()
        WorkbenchStyle.mint.withAlphaComponent(0.55).setStroke(); NSBezierPath(roundedRect: board.insetBy(dx: 0.5, dy: 0.5), xRadius: 16, yRadius: 16).stroke()
        for y in stride(from: 44, through: 108, by: 16) {
            for x in [68, 165] { WorkbenchStyle.mint.withAlphaComponent(0.65).setFill(); NSBezierPath(roundedRect: NSRect(x: x, y: y, width: 7, height: 5), xRadius: 2, yRadius: 2).fill() }
        }
        WorkbenchStyle.ink.setFill(); NSBezierPath(roundedRect: NSRect(x: 94, y: 44, width: 52, height: 53), xRadius: 10, yRadius: 10).fill()
        let rune = NSBezierPath(); rune.move(to: NSPoint(x: 111, y: 58)); rune.line(to: NSPoint(x: 130, y: 79)); rune.line(to: NSPoint(x: 120, y: 88)); rune.line(to: NSPoint(x: 120, y: 51)); rune.line(to: NSPoint(x: 130, y: 61)); rune.line(to: NSPoint(x: 111, y: 81)); rune.lineWidth = 2.5; rune.lineJoinStyle = .round; WorkbenchStyle.mint.setStroke(); rune.stroke()
        WorkbenchStyle.mint.setFill(); NSBezierPath(ovalIn: NSRect(x: 98, y: 108, width: 5, height: 5)).fill()
        NSColor.white.withAlphaComponent(0.55).setFill(); NSBezierPath(roundedRect: NSRect(x: 111, y: 116, width: 18, height: 13), xRadius: 3, yRadius: 3).fill()
        for (x,y) in [(47,55), (191,93)] { WorkbenchStyle.mint.setFill(); NSBezierPath(ovalIn: NSRect(x:x,y:y,width:5,height:5)).fill() }
    }
}
