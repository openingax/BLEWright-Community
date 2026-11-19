#!/bin/sh
set -eu
firmware_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
app="$firmware_root/build/BLEWrightHardwareFixture.app"
mkdir -p "$app/Contents/MacOS"
cat > "$app/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd"><plist version="1.0"><dict><key>CFBundleIdentifier</key><string>space.nomoloop.blewright.hardwarefixture</string><key>CFBundleName</key><string>BLEWright hardware fixture</string><key>CFBundleExecutable</key><string>Fixture</string><key>CFBundlePackageType</key><string>APPL</string><key>NSBluetoothAlwaysUsageDescription</key><string>BLEWright uses Bluetooth to test the connected ESP32-S3 development board.</string></dict></plist>
PLIST
xcrun swiftc "$firmware_root/tools/PeripheralFixture.swift" -o "$app/Contents/MacOS/Fixture" -framework AppKit -framework CoreBluetooth
codesign --force --sign - "$app"
printf '%s\n' "$app"
