# Run BLEWright on your Mac

[中文](guide.zh.md) · [Project overview](../README.md)

Run commands in the root of your BLEWright checkout. Start with the mock peripheral to verify your app and the Mac service independently of USB and radio conditions.

## 1. Start a mock peripheral

Install Node.js 20 or newer. Keep the following service running in a terminal.

```sh
npm ci
npm run serve
```

Look for a JSON line containing `"event":"listening"` and `"backend":"mock"`. The service listens on the Mac loopback interface. Each client gets a peripheral called **BLEWright**, with service **FFF0** and characteristic **FFF1**. Reading FFF1 on a fresh connection returns the bytes `42 4c 45` (ASCII `BLE`). A successful write changes the value returned by the next read.

| Backend | Default TCP port | What to expect |
| --- | --- | --- |
| Mock | 8765 | One generated peripheral per session |
| ESP32-S3 | 8876 | Advertisements from nearby devices and a single active connection |
| Passive scan | 8766 | Advertisements only, when the scan-only service is enabled |

## 2. Try your iOS app

1. In Xcode, open the app project and choose **File → Add Package Dependencies → Add Local**. Select the BLEWright checkout root and link the **SimulatorBLE** product to your app target. For a remote dependency, enter `https://github.com/openingax/BLEWright-Community.git` in the package search field and choose version `0.1.0`.
2. In the app target's **Build Settings → Other Linker Flags**, expand **Debug** and add an **Any iOS Simulator SDK** condition. Preserve inherited flags and add `-ObjC`. This loads the Objective-C class that installs the adapter at launch.
3. Duplicate your development scheme. In **Edit Scheme → Run → Info**, select **Debug**. Under **Arguments → Environment Variables**, enable `BLEWRIGHT_ENABLE=1` and `BLEWRIGHT_PORT=8765`.
4. Choose an iPhone Simulator, launch the app and open its normal scan screen. The Xcode console should contain `SimulatorBLE installed`. Apps filtering advertisements by a product-specific UUID or name may hide the mock. Use an unfiltered scan or the standalone probe below.
5. To return to standard behavior, remove the enable variable and relaunch. Hooks compile only for Debug Simulator. Physical-device and Release builds retain native CoreBluetooth behavior. Your dependencies must themselves contain a compatible simulator binary.

To exercise the included probe, install XcodeGen, start an iPhone simulator in Xcode and copy its UUID from `xcrun simctl list devices booted`. The verifier starts its own temporary services.

```sh
read -r 'simulator_id?Booted simulator UUID: '
npm run build:ios -- --simulator "$simulator_id"
npm run verify:ios -- --simulator "$simulator_id"
```

The prompt command above uses the default macOS shell, zsh. The probe exercises callbacks, data exchange and service loss. Runtime-based bridging depends on the iOS Simulator implementation. Repeat the probe after upgrading Xcode.

## 3. Try the Android sample

Use a root-capable Android 15 / API 35 development AVD with a Bluetooth adapter. Install JDK 17, Android SDK Platform 35, Build Tools 36.0.0 and Platform Tools. Put `adb` on your PATH. The build scripts use `$HOME/Library/Android/sdk` by default and accept `ANDROID_SDK_ROOT` and `JAVA_HOME` overrides. Use an emulator and a sample or development app you control.

Install the launcher from the checkout and build the included BLE Explorer app.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r android/launcher/requirements.txt
npm run build:android
npm run build:explorer
adb devices -l
```

Set `avd` to the running emulator serial. Download the Android **frida-server 17.5.1** archive matching the ABI printed below (`arm64-v8a` maps to `android-arm64`). Decompress it and place the executable at `/tmp/frida-server`. The host dependency and server versions must match. [Frida 17.5.1 release](https://github.com/frida/frida/releases/tag/17.5.1)

```sh
avd=emulator-5554
adb -s "$avd" shell getprop ro.product.cpu.abi
adb -s "$avd" root
adb -s "$avd" wait-for-device
adb -s "$avd" push /tmp/frida-server /data/local/tmp/blewright-frida-server
adb -s "$avd" shell chmod 755 /data/local/tmp/blewright-frida-server
adb -s "$avd" shell '/data/local/tmp/blewright-frida-server >/data/local/tmp/blewright-frida.log 2>&1 &'
adb -s "$avd" install -r -g dist/android/explorer/blewright-explorer.apk
npm run explorer:mock -- --serial "$avd"
```

This launcher starts a dedicated mock service. In BLE Explorer, scan, select **BLEWright**, connect, discover services and read **FFF1**. Leave the launcher running while using the app. Ctrl-C ends the launched session. For the hardware service from step 4, start the installed sample with:

```sh
npm run android:run -- --serial "$avd" --package space.nomoloop.blewright.explorer --rpc-port 8876
```

## 4. Switch to a real peripheral

Use an ESP32-S3 board with a **native USB Serial/JTAG** connector, a data cable and a separate BLE peripheral you control. The checked-in configuration targets **16 MB flash**. Check the board specification before flashing. Flashing replaces the bridge board's current firmware. Identify the bridge by unplugging it and comparing the port list before and after reconnection.

In a shell with ESP-IDF **v5.5.1** installed and activated, run:

```sh
python -m serial.tools.list_ports -v
read -r 'bridge_port?ESP32-S3 USB port: '
idf.py -C firmware set-target esp32s3
idf.py -C firmware build
idf.py -C firmware -p "$bridge_port" flash
```

Close any serial monitor. In the same shell, create the repo venv if needed, install the serial dependency and launch the service. Only one process can own the USB connection.

```sh
test -x .venv/bin/python || python3 -m venv .venv
.venv/bin/python -m pip install -r firmware/tools/requirements.txt
BLEWRIGHT_BACKEND=esp32 BLEWRIGHT_SERIAL="$bridge_port" npm run serve
```

Wait for `boardReady`, then `listening` with backend `esp32`. Select port **8876** in the simulator client and relaunch. Put your peripheral in advertising mode and start a scan. Choose your device, connect and discover its services. The connected peripheral determines which reads, writes and subscriptions are available. The bridge negotiates ATT MTU with the peripheral; applications should query the write limit for the current connection.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| iOS reports Bluetooth off | Check for the installation log. If missing, verify the destination, Debug scheme, linker flag and enabled environment variable. If present, verify the service's listening port and relaunch. |
| Connection succeeds but the app lists no devices | Try an unfiltered scan. The mock advertises FFF0. For hardware, check that the device is advertising and the service reports `esp32`. |
| Hardware returns `BUSY` | Stop the former simulator client and let the session close before starting another. Close the serial monitor before restarting the service. |
| USB port appears but no `boardReady` | Check the connector, firmware target and selected serial port. A USB-to-UART port may appear in the list even though the firmware exchanges frames on the board's native USB interface. |
| Android reports unsupported API or root failure | Check `ro.build.version.sdk` for 35 and use a root-capable development AVD. Check the ABI and exact Frida versions on both ends. |
| Data transfer stalls after connecting | Compare the negotiated write length with the application's payload size. The backend supports single ATT payloads and notifications. Use device-specific fragmentation when the peripheral protocol requires it. |
