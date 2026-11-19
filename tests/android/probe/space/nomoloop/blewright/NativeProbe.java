package space.nomoloop.blewright;

import android.Manifest;
import android.bluetooth.*;
import android.bluetooth.le.*;
import android.content.Context;
import android.content.pm.PackageManager;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.Looper;
import android.os.ParcelUuid;
import android.util.Log;
import java.util.Arrays;
import java.util.Collections;
import java.util.UUID;

/** Uses only public Android BLE APIs: no SimulatorBLE imports or custom BLE objects. */
@SuppressWarnings("deprecation")
public final class NativeProbe {
    private static final String TAG = "BLEWrightProbe";
    private static final UUID SERVICE = UUID.fromString("0000fff0-0000-1000-8000-00805f9b34fb");
    private static final UUID CHAR = UUID.fromString("0000fff1-0000-1000-8000-00805f9b34fb");
    private static final UUID CCCD = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb");
    private byte[] VALUE = new byte[]{1, 2, 3, 4};
    private boolean hardware;
    private static String targetAddress;
    private static byte[] targetNonce;
    public static void configureTarget(String address, String nonce) {
        targetAddress = address;
        targetNonce = new byte[4];
        for (int i=0; i<4; i++) targetNonce[i]=(byte)Integer.parseInt(nonce.substring(i*2,i*2+2),16);
    }
    private ScanFilter targetFilter() {
        ScanFilter.Builder b = new ScanFilter.Builder().setServiceUuid(new ParcelUuid(SERVICE));
        if (hardware && targetAddress != null) b.setDeviceAddress(targetAddress).setManufacturerData(65535,targetNonce);
        return b.build();
    }
    public static volatile String result = "NOT_STARTED";
    private static NativeProbe active;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private Context context;
    private HandlerThread callbackThread;
    private Handler callbackHandler;
    private boolean duplicateFailed;
    private BluetoothLeScanner scanner;
    private BluetoothGatt gatt;
    private BluetoothGattCharacteristic characteristic;
    private boolean modern, readDone, notified, finished, disconnecting;
    private int stage;
    private int companionResults;
    private final ScanCallback companion = new ScanCallback() {
        @Override public void onScanResult(int type, ScanResult value) {
            companionResults++;
            scanner.stopScan(this);
        }
        @Override public void onScanFailed(int error) { finish("FAIL: shared scan " + error); }
    };
    private final ScanCallback unmatched = new ScanCallback() {
        @Override public void onScanResult(int type, ScanResult value) { finish("FAIL: unmatched shared scan"); }
        @Override public void onScanFailed(int error) { finish("FAIL: unmatched shared scan error " + error); }
    };

    public static void start(Context context) {
        start(context, false);
    }
    public static void startHardware(Context context) {
        start(context, true);
    }
    private static void start(Context context, boolean hardware) {
        if (active != null && !active.finished) throw new IllegalStateException("Probe already running");
        active = new NativeProbe();
        active.context = context;
        active.hardware = hardware;
        result = "RUNNING";
        active.handler.post(() -> active.guard(() -> active.begin()));
    }
    private void check(boolean condition, String message) {
        if (!condition) throw new IllegalStateException(message);
    }
    private void guard(Runnable action) {
        if (finished) return;
        try { action.run(); } catch (Throwable e) { finish("FAIL: " + e); }
    }
    private void finish(String value) {
        if (finished) return;
        finished = true; result = value; Log.i(TAG, value);
        if (scanner != null) { scanner.stopScan(scan); scanner.stopScan(companion); scanner.stopScan(unmatched); }
        if (gatt != null) gatt.close();
        if (callbackThread != null) callbackThread.quitSafely();
    }
    private void begin() {
        check(context.checkSelfPermission(Manifest.permission.BLUETOOTH_SCAN) == PackageManager.PERMISSION_GRANTED, "BLUETOOTH_SCAN missing");
        check(context.checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) == PackageManager.PERMISSION_GRANTED, "BLUETOOTH_CONNECT missing");
        BluetoothManager manager = context.getSystemService(BluetoothManager.class);
        check(manager != null && manager.getAdapter() != null, "No adapter");
        scanner = manager.getAdapter().getBluetoothLeScanner();
        check(scanner != null, "No scanner");
        handler.postDelayed(() -> { if (!finished) finish("FAIL: timed out at stage " + stage + ", modern=" + modern); }, hardware ? 55000 : 12000);
        // A stopped scan and an unmatched filter must produce no result.
        ScanCallback forbidden = new ScanCallback() {
            @Override public void onScanResult(int type, ScanResult value) { finish("FAIL: stopped/unmatched scan delivered result"); }
            @Override public void onScanFailed(int error) { finish("FAIL: filter/stop scan error " + error); }
        };
        ScanCallback duplicate = new ScanCallback() {
            @Override public void onScanFailed(int error) {
                if (error == ScanCallback.SCAN_FAILED_ALREADY_STARTED) duplicateFailed=true;
                else finish("FAIL: wrong duplicate scan error " + error);
            }
        };
        scanner.startScan(duplicate); scanner.startScan(duplicate); scanner.stopScan(duplicate);
        scanner.startScan(forbidden); scanner.stopScan(forbidden);
        scanner.startScan(Collections.singletonList(new ScanFilter.Builder().setDeviceName("does-not-exist").build()), new ScanSettings.Builder().build(), forbidden);
        handler.postDelayed(() -> guard(() -> { scanner.stopScan(forbidden); check(duplicateFailed,"duplicate scan failure missing"); startRound(); }), 200);
    }
    private void startRound() {
        stage=0; readDone=false; notified=false; disconnecting=false;
        if (hardware) VALUE = new byte[]{16, 32, (byte)(System.nanoTime() & 255), (byte)(modern ? 2 : 1)};
        companionResults=0;
        scanner.startScan(Collections.singletonList(new ScanFilter.Builder().setDeviceName("does-not-exist").build()), new ScanSettings.Builder().build(), unmatched);
        scanner.startScan(Collections.singletonList(targetFilter()), new ScanSettings.Builder().build(), companion);
        scanner.startScan(Collections.singletonList(targetFilter()), new ScanSettings.Builder().build(), scan);
    }
    private final ScanCallback scan = new ScanCallback() {
        @Override public void onScanFailed(int error) { finish("FAIL: scan error " + error); }
        @Override public void onScanResult(int type, ScanResult value) { guard(() -> {
            check(stage==0, "duplicate scan"); stage=1;
            check(companionResults==1, "concurrent scan did not receive result");
            check(value.getScanRecord()!=null && (hardware ? "BLEWright-C6" : "BLEWright").equals(value.getScanRecord().getDeviceName()), "bad scan record");
            scanner.stopScan(this);
            scanner.stopScan(unmatched);
            if (modern) gatt=value.getDevice().connectGatt(context,false,callback,BluetoothDevice.TRANSPORT_LE,BluetoothDevice.PHY_LE_1M_MASK,callbackHandler);
            else gatt=value.getDevice().connectGatt(context,false,callback);
            check(gatt!=null, "null GATT");
            check(gatt.getClass()==BluetoothGatt.class, "not an Android BluetoothGatt");
        }); }
    };
    private void receivedRead(BluetoothGatt g, BluetoothGattCharacteristic c, byte[] value, int status) { guard(() -> {
        check(stage==4 && status==0 && Arrays.equals(value,VALUE), "read roundtrip mismatch");
        check(c==characteristic && g==gatt, "object identity mismatch");
        readDone=true; maybeDisconnect();
    }); }
    private void receivedNotify(BluetoothGatt g, BluetoothGattCharacteristic c, byte[] value) { guard(() -> {
        check(c==characteristic && g==gatt, "notification object identity mismatch");
        if (Arrays.equals(value,VALUE)) { notified=true; maybeDisconnect(); }
    }); }
    private void maybeDisconnect() {
        if (!readDone || !notified || disconnecting) return;
        disconnecting=true; stage=5;
        check(gatt.setCharacteristicNotification(characteristic,false), "unsubscribe rejected");
        gatt.disconnect(); gatt.disconnect();
    }
    // Both modern and deprecated callback signatures must work; the deprecated round relies
    // on Android's default modern -> legacy callback forwarding, not agent double-dispatch.
    private BluetoothGattCallback callbacks(boolean modernCallbacks) {
        if (modernCallbacks) return new BaseCallbacks() {
            @Override public void onCharacteristicRead(BluetoothGatt g,BluetoothGattCharacteristic c,byte[] value,int status) { receivedRead(g,c,value,status); }
            @Override public void onCharacteristicChanged(BluetoothGatt g,BluetoothGattCharacteristic c,byte[] value) { receivedNotify(g,c,value); }
        };
        return new BaseCallbacks() {
            @Override public void onCharacteristicRead(BluetoothGatt g,BluetoothGattCharacteristic c,int status) { receivedRead(g,c,c.getValue(),status); }
            @Override public void onCharacteristicChanged(BluetoothGatt g,BluetoothGattCharacteristic c) { receivedNotify(g,c,c.getValue()); }
        };
    }
    private BluetoothGattCallback callback = callbacks(false);
    private class BaseCallbacks extends BluetoothGattCallback {
        @Override public void onConnectionStateChange(BluetoothGatt g,int status,int state) { guard(() -> {
            check(!modern || Looper.myLooper()==callbackHandler.getLooper(), "wrong callback Handler");
            check(status==0 && g==gatt, "connection failure or identity mismatch");
            if (state==BluetoothProfile.STATE_CONNECTED) {
                check(stage==1, "unexpected connection"); stage=2;
                check(g.discoverServices(), "discovery rejected");
            } else if (state==BluetoothProfile.STATE_DISCONNECTED) {
                check(stage==5, "early disconnect"); g.close();
                Log.i(TAG,"ROUND_PASS " + (modern?"modern":"legacy"));
                if (!modern) {modern=true;callbackThread=new HandlerThread("BLEWrightProbeCallbacks");callbackThread.start();callbackHandler=new Handler(callbackThread.getLooper());callback=callbacks(true);handler.postDelayed(() -> guard(() -> startRound()),80);}
                else {
                    BluetoothGatt canceled=g.getDevice().connectGatt(context,false,new BluetoothGattCallback(){
                        @Override public void onConnectionStateChange(BluetoothGatt unused,int code,int next){finish("FAIL: callback after close");}
                    });
                    check(canceled!=null,"cancel test GATT null");canceled.close();
                    handler.postDelayed(() -> finish("PASS: native scan/filter/stop/duplicate, connectGatt, service identity, legacy+modern write/read/notify, callback Handler, disconnect/close/cancel"),150);
                }
            }
        }); }
        @Override public void onServicesDiscovered(BluetoothGatt g,int status) { guard(() -> {
            check(stage==2 && status==0, "discovery failure"); stage=3;
            BluetoothGattService service=g.getService(SERVICE);
            check(service!=null && (hardware || g.getServices().size()==1), "missing services");
            check(g.getService(SERVICE)==service && g.getServices().contains(service), "cached service handle invalidated after return");
            characteristic=service.getCharacteristic(CHAR);
            check(characteristic!=null && characteristic.getService()==service, "missing characteristic relationship");
            check(g.setCharacteristicNotification(characteristic,true), "local notify rejected");
            BluetoothGattDescriptor d=characteristic.getDescriptor(CCCD);
            check(d!=null && d.getCharacteristic()==characteristic, "missing descriptor relationship");
            if(modern)check(g.writeDescriptor(d,BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE)==0,"CCCD rejected");
            else {d.setValue(BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE);check(g.writeDescriptor(d),"legacy CCCD rejected");}
        }); }
        @Override public void onDescriptorWrite(BluetoothGatt g,BluetoothGattDescriptor d,int status) { guard(() -> {
            check(stage==3 && status==0,"CCCD failure");stage=4;
            if(modern)check(g.writeCharacteristic(characteristic,VALUE,BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT)==0,"write rejected");
            else {characteristic.setValue(VALUE);characteristic.setWriteType(BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT);check(g.writeCharacteristic(characteristic),"legacy write rejected");}
        }); }
        @Override public void onCharacteristicWrite(BluetoothGatt g,BluetoothGattCharacteristic c,int status) { guard(() -> {
            check(stage==4 && status==0,"write failure");check(g.readCharacteristic(c),"read rejected");
        }); }
    }
}
