package space.nomoloop.blewright.explorer;

import android.Manifest;
import android.bluetooth.*;
import android.bluetooth.le.*;
import android.content.Context;
import android.content.pm.PackageManager;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import java.nio.ByteBuffer;
import java.nio.charset.*;
import java.text.SimpleDateFormat;
import java.util.*;

/** Native Android BLE only. No RPC, fixtures, Frida or transport-specific branches. */
final class BleClient {
    interface Listener { void changed(); }
    static final UUID CCCD = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb");
    final Context context;
    final Handler main = new Handler(Looper.getMainLooper());
    final Listener listener;
    final LinkedHashMap<String, ScanResult> devices = new LinkedHashMap<>();
    final ArrayList<String> logs = new ArrayList<>();
    final ArrayList<BluetoothGattService> services = new ArrayList<>();
    final Map<BluetoothGattCharacteristic, byte[]> values = new HashMap<>();
    final Set<BluetoothGattCharacteristic> subscriptions = new HashSet<>();
    BluetoothAdapter adapter;
    BluetoothGatt gatt;
    BluetoothDevice selected;
    BluetoothLeScanner scanner;
    ScanCallback scanCallback;
    String availability = "正在检查蓝牙", state = "未连接", scanState = "尚未扫描";
    String pending;
    BluetoothGattCharacteristic pendingCharacteristic;
    boolean pendingSubscribe;
    boolean active;
    boolean ready;
    Runnable scanTimeout, operationTimeout;

    BleClient(Context context, Listener listener) {
        this.context = context.getApplicationContext();
        this.listener = listener;
        BluetoothManager manager = this.context.getSystemService(BluetoothManager.class);
        adapter = manager == null ? null : manager.getAdapter();
    }
    boolean permitted() {
        return context.checkSelfPermission(Manifest.permission.BLUETOOTH_SCAN) == PackageManager.PERMISSION_GRANTED
            && context.checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) == PackageManager.PERMISSION_GRANTED;
    }
    boolean usable() {
        try { return permitted() && adapter != null && adapter.isEnabled(); }
        catch (RuntimeException e) { return false; }
    }
    void log(String message) {
        String line = new SimpleDateFormat("HH:mm:ss.SSS", Locale.ROOT).format(new Date()) + "  " + message;
        logs.add(line);
        if (logs.size() > 300) logs.remove(0);
        Log.i("BLEExplorer", message);
    }
    void changed() { listener.changed(); }
    final Runnable poll = new Runnable() {
        public void run() {
            if (!active) return;
            refresh();
            main.postDelayed(this, 1000);
        }
    };
    void resume() { active = true; main.removeCallbacks(poll); poll.run(); }
    void refresh() {
        String next = !permitted() ? "需要附近设备权限" : adapter == null ? "设备没有蓝牙适配器"
            : usable() ? "蓝牙可用" : "蓝牙不可用，请开启蓝牙或检查外部连接";
        if (!next.equals(availability)) {
            availability = next;
            log(next);
            if (!usable()) {
                stopScan("扫描已停止：蓝牙或权限不可用");
                if (gatt != null) release("连接已关闭：蓝牙或权限不可用");
            }
            changed();
        }
    }
    void pause() {
        active = false;
        main.removeCallbacks(poll);
        stopScan("扫描已停止：离开页面");
        if (gatt != null) release("已断开：离开页面");
    }
    void startScan() {
        if (scanCallback != null) return;
        refresh();
        if (!usable()) { log("扫描未开始：" + availability); changed(); return; }
        if (gatt != null) { log("请先断开当前设备再扫描"); changed(); return; }
        devices.clear();
        scanState = "扫描中 · 最长 15 秒";
        ScanCallback callback = new ScanCallback() {
            @Override public void onScanResult(int type, ScanResult result) {
                main.post(() -> {
                    if (scanCallback != this) return;
                    String address = result.getDevice().getAddress();
                    if (devices.containsKey(address) || devices.size() < 200) devices.put(address, result);
                    changed();
                });
            }
            @Override public void onBatchScanResults(List<ScanResult> results) {
                for (ScanResult result : results) onScanResult(0, result);
            }
            @Override public void onScanFailed(int code) {
                main.post(() -> {
                    if (scanCallback != this) return;
                    stopScan("扫描失败 · 错误码 " + code);
                });
            }
        };
        scanCallback = callback;
        try {
            scanner = adapter.getBluetoothLeScanner();
            if (scanner == null) throw new IllegalStateException("扫描器不可用");
            scanner.startScan(null, new ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).build(), callback);
            log("开始扫描");
            scanTimeout = () -> { if (scanCallback == callback) stopScan("扫描结束 · " + devices.size() + " 台设备"); };
            main.postDelayed(scanTimeout, 15000);
        } catch (RuntimeException e) { stopScan("扫描失败：" + error(e)); }
        changed();
    }
    void stopScan(String reason) {
        ScanCallback old = scanCallback;
        scanCallback = null;
        if (scanTimeout != null) main.removeCallbacks(scanTimeout);
        scanTimeout = null;
        if (old == null) return;
        try { if (scanner != null) scanner.stopScan(old); }
        catch (RuntimeException e) { log("停止扫描：" + error(e)); }
        scanner = null;
        scanState = reason;
        log(reason);
        changed();
    }
    void connect(ScanResult result) {
        if (!usable()) { refresh(); return; }
        stopScan("扫描已停止：连接设备");
        if (gatt != null) release("已关闭上一连接");
        selected = result.getDevice();
        state = "连接中";
        log("连接 " + selected.getAddress());
        try {
            gatt = selected.connectGatt(context, false, callback, BluetoothDevice.TRANSPORT_LE, BluetoothDevice.PHY_LE_1M_MASK, main);
            if (gatt == null) throw new IllegalStateException("系统未创建连接");
            begin("连接", null);
        } catch (RuntimeException e) { release("连接失败：" + error(e)); }
        changed();
    }
    void begin(String operation, BluetoothGattCharacteristic characteristic) {
        pending = operation;
        pendingCharacteristic = characteristic;
        BluetoothGatt owner = gatt;
        operationTimeout = () -> {
            if (gatt == owner && pending != null) release(pending + "超时；连接已关闭，请重连");
        };
        main.postDelayed(operationTimeout, 12000);
    }
    void finish() {
        if (operationTimeout != null) main.removeCallbacks(operationTimeout);
        operationTimeout = null;
        pending = null;
        pendingCharacteristic = null;
    }
    boolean canOperate() { return usable() && gatt != null && ready && pending == null; }
    void release(String reason) {
        BluetoothGatt old = gatt;
        gatt = null;
        ready = false;
        finish();
        services.clear(); values.clear(); subscriptions.clear();
        if (old != null) {
            try { old.disconnect(); } catch (RuntimeException e) { log("断开请求：" + error(e)); }
            try { old.close(); } catch (RuntimeException e) { log("关闭连接：" + error(e)); }
        }
        state = reason;
        log(reason);
        changed();
    }
    void read(BluetoothGattCharacteristic c) {
        if (!canOperate()) return;
        begin("读取", c);
        try {
            if (!gatt.readCharacteristic(c)) throw new IllegalStateException("系统拒绝读取");
            log("读取请求 " + c.getUuid());
        } catch (RuntimeException e) { finish(); log("读取失败：" + error(e)); }
        changed();
    }
    void write(BluetoothGattCharacteristic c, byte[] value, int type) {
        if (!canOperate()) return;
        begin("写入", c);
        try {
            int status = gatt.writeCharacteristic(c, value, type);
            if (status != BluetoothStatusCodes.SUCCESS) throw new IllegalStateException("提交错误码 " + status);
            log("写入请求 " + c.getUuid() + " · " + hex(value) + (type == BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE ? " · 无响应写入（不确认外设接收）" : " · 有响应写入"));
        } catch (RuntimeException e) { finish(); log("写入失败：" + error(e)); }
        changed();
    }
    void subscribe(BluetoothGattCharacteristic c) {
        if (!canOperate()) return;
        BluetoothGattDescriptor descriptor = c.getDescriptor(CCCD);
        if (descriptor == null) { log("无法订阅：缺少 CCCD 描述符"); changed(); return; }
        boolean enable = !subscriptions.contains(c);
        begin("订阅", c);
        pendingSubscribe = enable;
        try {
            if (!gatt.setCharacteristicNotification(c, enable)) throw new IllegalStateException("本地通知注册失败");
            byte[] bytes = !enable ? BluetoothGattDescriptor.DISABLE_NOTIFICATION_VALUE
                : (c.getProperties() & BluetoothGattCharacteristic.PROPERTY_NOTIFY) != 0
                ? BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE : BluetoothGattDescriptor.ENABLE_INDICATION_VALUE;
            int status = gatt.writeDescriptor(descriptor, bytes);
            if (status != BluetoothStatusCodes.SUCCESS) throw new IllegalStateException("CCCD 提交错误码 " + status);
            log(enable ? "请求订阅通知" : "请求取消订阅");
        } catch (RuntimeException e) {
            rollbackNotification(c);
            finish(); log("订阅失败：" + error(e));
        }
        changed();
    }
    void rollbackNotification(BluetoothGattCharacteristic c) {
        try { if (gatt != null) gatt.setCharacteristicNotification(c, subscriptions.contains(c)); }
        catch (RuntimeException e) { log("恢复通知注册失败：" + error(e)); }
    }
    boolean matches(BluetoothGatt owner, String operation, BluetoothGattCharacteristic c) {
        return gatt == owner && operation.equals(pending) && c == pendingCharacteristic;
    }
    final BluetoothGattCallback callback = new BluetoothGattCallback() {
        @Override public void onConnectionStateChange(BluetoothGatt owner, int status, int newState) {
            main.post(() -> {
                if (owner != gatt) return;
                log("连接回调 · status=" + status + " state=" + newState);
                if (status != BluetoothGatt.GATT_SUCCESS || newState == BluetoothProfile.STATE_DISCONNECTED) {
                    release("已断开 · 状态码 " + status); return;
                }
                if (newState == BluetoothProfile.STATE_CONNECTED && "连接".equals(pending)) {
                    finish(); state = "已连接 · 正在发现服务";
                    begin("发现服务", null);
                    try {
                        if (!owner.discoverServices()) throw new IllegalStateException("系统拒绝发现服务");
                    } catch (RuntimeException e) { release("服务发现失败：" + error(e)); }
                    changed();
                }
            });
        }
        @Override public void onServicesDiscovered(BluetoothGatt owner, int status) {
            main.post(() -> {
                if (!matches(owner, "发现服务", null)) return;
                finish();
                if (status != 0) { release("服务发现失败 · 状态码 " + status); return; }
                services.clear(); services.addAll(owner.getServices());
                ready = true; state = "已连接 · " + services.size() + " 个服务";
                log("服务发现成功 · " + services.size() + " 个服务"); changed();
            });
        }
        @Override public void onCharacteristicRead(BluetoothGatt owner, BluetoothGattCharacteristic c, byte[] bytes, int status) {
            byte[] snapshot = bytes.clone();
            main.post(() -> {
                if (!matches(owner, "读取", c)) return;
                finish();
                if (status == 0) values.put(c, snapshot);
                log("读取回调 · 状态码 " + status + " · " + hex(snapshot)); changed();
            });
        }
        @Override public void onCharacteristicWrite(BluetoothGatt owner, BluetoothGattCharacteristic c, int status) {
            main.post(() -> {
                if (!matches(owner, "写入", c)) return;
                finish(); log("写入回调 · 状态码 " + status + " · 读取可核对设备值"); changed();
            });
        }
        @Override public void onDescriptorWrite(BluetoothGatt owner, BluetoothGattDescriptor descriptor, int status) {
            main.post(() -> {
                BluetoothGattCharacteristic c = descriptor.getCharacteristic();
                if (!matches(owner, "订阅", c) || !CCCD.equals(descriptor.getUuid())) return;
                if (status == 0) {
                    if (pendingSubscribe) subscriptions.add(c); else subscriptions.remove(c);
                } else rollbackNotification(c);
                log("CCCD 回调 · 状态码 " + status + " · " + (subscriptions.contains(c) ? "已订阅" : "未订阅"));
                finish(); changed();
            });
        }
        @Override public void onCharacteristicChanged(BluetoothGatt owner, BluetoothGattCharacteristic c, byte[] bytes) {
            byte[] snapshot = bytes.clone();
            main.post(() -> {
                if (owner != gatt || !subscriptions.contains(c)) return;
                values.put(c, snapshot); log("收到通知 · " + c.getUuid() + " · " + hex(snapshot)); changed();
            });
        }
    };
    static String error(RuntimeException e) { return e.getClass().getSimpleName() + ": " + e.getMessage(); }
    static String hex(byte[] bytes) {
        if (bytes == null || bytes.length == 0) return "（空）";
        StringBuilder text = new StringBuilder();
        for (byte b : bytes) { if (text.length() > 0) text.append(' '); text.append(String.format(Locale.ROOT, "%02X", b & 255)); }
        return text.toString();
    }
    static byte[] parseHex(String input) {
        String text = input.replaceAll("\\s", "");
        if (text.isEmpty() || text.length() % 2 != 0 || !text.matches("[0-9a-fA-F]+"))
            throw new IllegalArgumentException("请输入成对的十六进制字节，例如 01 02 FF");
        if (text.length() > 1024) throw new IllegalArgumentException("最多输入 512 字节；设备可能有更小的长度限制");
        byte[] result = new byte[text.length() / 2];
        for (int i = 0; i < result.length; i++) result[i] = (byte) Integer.parseInt(text.substring(i * 2, i * 2 + 2), 16);
        return result;
    }
    static String utf8(byte[] bytes) {
        try {
            String text = StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString();
            return text.replaceAll("[\\p{Cntrl}&&[^\\n\\t]]", "·");
        } catch (CharacterCodingException e) { return "（非 UTF-8 文本）"; }
    }
    static String name(ScanResult result) {
        String name = result.getScanRecord() == null ? null : result.getScanRecord().getDeviceName();
        return ScanFilterState.hasName(name) ? name.trim() : "未命名设备";
    }
}
