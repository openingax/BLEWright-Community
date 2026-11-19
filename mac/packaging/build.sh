#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
base="$PWD"
version=$(.venv/bin/python -c 'import json; print(json.load(open("mac/packaging/release.json"))["version"])')
arch=$(uname -m)
[[ "$arch" == arm64 ]] || { echo '当前包仅支持 Apple Silicon，请在 arm64 Mac 构建'; exit 1; }
stage="$base/dist/mac-pkg-root"
build="$base/dist/mac-build"
mkdir -p "$build"
# Download a pinned official standalone runtime; no Homebrew dependency on end-user Macs.
node_version=v26.13.0
archive="node-$node_version-darwin-arm64.tar.gz"
if [[ ! -f "$build/$archive" ]]; then
  curl -fL "https://nodejs.org/dist/$node_version/$archive" -o "$build/$archive"
fi
# Digest recorded from the official SHASUMS256.txt for this exact platform and release.
node_sha256=d38bd5e5a2ddce6bbb5ce45e46e208337da4d51fffe611e567fd32073d6439f6
(cd "$build"; printf '%s  %s\n' "$node_sha256" "$archive" | shasum -a 256 -c -)
rm -rf "$stage"
app="$stage/Applications/BLEWright.app"
support="$stage/Library/Application Support/BLEWright"
mkdir -p "$app/Contents/MacOS" "$support/runtime" "$support/resources" "$stage/Library/LaunchDaemons" "$stage/Library/LaunchAgents"
xcrun swiftc -swift-version 5 -O -target arm64-apple-macosx13.0 mac/desktop/main.swift mac/desktop/Design.swift -framework AppKit -o "$app/Contents/MacOS/BLEWright"
mkdir -p "$app/Contents/Resources"
cp mac/desktop/Resources/AppIcon.icns "$app/Contents/Resources/"
cat > "$app/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd"><plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>dev.blewright.mac</string><key>CFBundleName</key><string>BLEWright</string>
<key>CFBundleIconFile</key><string>AppIcon</string>
<key>CFBundleExecutable</key><string>BLEWright</string><key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>0.4.0</string><key>CFBundleVersion</key><string>5</string>
<key>LSMinimumSystemVersion</key><string>13.0</string><key>LSUIElement</key><true/>
</dict></plist>
PLIST
.venv/bin/python - "$app/Contents/Info.plist" <<'PYINFO'
import json, plistlib, sys
from pathlib import Path
release = json.loads(Path('mac/packaging/release.json').read_text())
p = Path(sys.argv[1]); info = plistlib.loads(p.read_bytes())
info.update(CFBundleShortVersionString=release['version'], CFBundleVersion=release['build'])
p.write_bytes(plistlib.dumps(info))
PYINFO
.venv/bin/python -m PyInstaller --noconfirm --clean --onedir --name BLEWrightRuntime \
 --distpath "$build/frozen" --workpath "$build/pyinstaller" --specpath "$build" \
 --paths mac/manager --hidden-import serial --hidden-import serial.tools.list_ports \
 --hidden-import serial_client --paths firmware/tools --collect-all esptool mac/manager/entry.py > "$build/pyinstaller.log" 2>&1
cp -R "$build/frozen/BLEWrightRuntime/." "$support/runtime/"
tar -xzf "$build/$archive" -C "$build"
cp "$build/node-$node_version-darwin-arm64/bin/node" "$support/runtime/node"
cp "$build/node-$node_version-darwin-arm64/LICENSE" "$support/runtime/NODE-LICENSE"
mkdir -p "$support/resources/mac"
cp -R mac/service mac/backends "$support/resources/mac/"
find "$support/resources/mac" -name '*.md' -delete
cp -R protocol "$support/resources/"
mkdir -p "$support/resources/firmware/tools" "$support/resources/firmware/release"
cp firmware/tools/serial_client.py "$support/resources/firmware/tools/"
.venv/bin/python - "$support/resources/firmware/release" <<'PY'
import hashlib,json,pathlib,shutil,sys
out=pathlib.Path(sys.argv[1]); source=pathlib.Path('firmware/build')
files=[]
for offset,name in json.loads((source/'flasher_args.json').read_text())['flash_files'].items():
    src=source/name; dest=out/src.name; shutil.copy2(src,dest)
    files.append(dict(offset=offset,file=dest.name,sha256=hashlib.sha256(dest.read_bytes()).hexdigest()))
(out/'manifest.json').write_text(json.dumps(dict(chip='esp32s3',files=files),indent=2))
PY
find "$support/resources" -name __pycache__ -type d -exec rm -rf {} +
cp mac/packaging/dev.blewright.daemon.plist "$stage/Library/LaunchDaemons/"
cp mac/packaging/dev.blewright.agent.plist "$stage/Library/LaunchAgents/"
# Developer ID identities can be supplied for distribution; otherwise make a local ad-hoc build.
identity="${APPLICATION_IDENTITY:--}"
codesign --force --options runtime --sign "$identity" "$app"
codesign --verify --deep --strict "$app"
codesign --force --options runtime --entitlements mac/packaging/node.entitlements --sign "$identity" "$support/runtime/node"
# PyInstaller signs nested runtime libraries; signing with a Developer ID requires rebuilding with that identity.
if [[ "$identity" != - ]]; then
  find "$support/runtime" -type f \( -name '*.dylib' -o -name '*.so' -o -name 'Python' -o -name 'BLEWrightRuntime' \) -exec codesign --force --options runtime --timestamp --sign "$identity" {} \;
  find "$support/runtime" -type d -name '*.framework' -exec codesign --force --options runtime --timestamp --sign "$identity" {} \;
fi
chmod -R go-w "$stage"
pkgbuild --analyze --root "$stage" "$build/components.plist"
/usr/libexec/PlistBuddy -c 'Set :0:BundleIsRelocatable false' "$build/components.plist"
pkgbuild --root "$stage" --component-plist "$build/components.plist" --scripts mac/packaging/scripts --identifier dev.blewright.pkg --version "$version" --install-location / --ownership recommended "$build/component.pkg"
cat > "$build/distribution.xml" <<XML
<installer-gui-script minSpecVersion="2"><title>BLEWright</title><options customize="never" require-scripts="false" hostArchitectures="arm64"/><domains enable_localSystem="true" enable_currentUserHome="false" enable_anywhere="false"/><allowed-os-versions><os-version min="13.0"/></allowed-os-versions><choices-outline><line choice="default"/></choices-outline><choice id="default" visible="false"><pkg-ref id="dev.blewright.pkg"/></choice><pkg-ref id="dev.blewright.pkg" version="$version">component.pkg</pkg-ref></installer-gui-script>
XML
productbuild --distribution "$build/distribution.xml" --package-path "$build" "$base/dist/BLEWright-$version-arm64.pkg"
if [[ -n "${INSTALLER_IDENTITY:-}" ]]; then
  productsign --sign "$INSTALLER_IDENTITY" "$base/dist/BLEWright-$version-arm64.pkg" "$base/dist/BLEWright-$version-arm64-signed.pkg"
fi
printf '输出：%s\n' "$base/dist/BLEWright-$version-arm64.pkg"
