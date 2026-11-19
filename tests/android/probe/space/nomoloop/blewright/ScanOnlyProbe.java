package space.nomoloop.blewright;

import android.bluetooth.BluetoothManager;
import android.bluetooth.le.*;
import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import java.util.Collections;

/** Read-only native scan. Never connects to or writes any peripheral. */
public final class ScanOnlyProbe {
    public static volatile String result = "NOT_STARTED";
    private static ScanOnlyProbe active;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private BluetoothLeScanner scanner;
    private boolean finished, stopped;
    private final ScanCallback callback = new ScanCallback() {
        @Override public void onScanFailed(int error) { finish("FAIL: scan " + error); }
        @Override public void onScanResult(int type, ScanResult value) {
            if (stopped) { finish("FAIL: callback after stop"); return; }
            if (value.getScanRecord() == null || !"BLEWright-C6".equals(value.getScanRecord().getDeviceName())) {
                finish("FAIL: scan filter mismatch"); return;
            }
            stopped = true;
            scanner.stopScan(this);
            handler.postDelayed(() -> finish("PASS: real read-only scan, native name filter and stop; no GATT requests"), 500);
        }
    };
    public static void start(Context context) {
        active = new ScanOnlyProbe();
        result = "RUNNING";
        active.handler.post(() -> active.begin(context));
    }
    private void begin(Context context) {
        try {
            scanner = context.getSystemService(BluetoothManager.class).getAdapter().getBluetoothLeScanner();
            scanner.startScan(Collections.singletonList(new ScanFilter.Builder().setDeviceName("BLEWright-C6").build()), new ScanSettings.Builder().build(), callback);
            handler.postDelayed(() -> finish("FAIL: no C6 advertisement within 12 seconds"), 12000);
        } catch (Throwable error) { finish("FAIL: " + error); }
    }
    private void finish(String message) {
        if (finished) return;
        finished = true;
        if (scanner != null) scanner.stopScan(callback);
        result = message;
    }
}
