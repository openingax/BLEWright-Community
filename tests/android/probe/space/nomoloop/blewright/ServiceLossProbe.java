package space.nomoloop.blewright;
import android.bluetooth.*;
import android.bluetooth.le.*;
import android.content.Context;
import android.os.Handler;
import android.os.Looper;

/** Public-API regression: a lost remote backend must not leave fake Bluetooth success. */
public final class ServiceLossProbe {
 public static volatile String result="NOT_STARTED";
 private static ServiceLossProbe active;
 private final Handler handler=new Handler(Looper.getMainLooper());
 private BluetoothAdapter adapter;
 private BluetoothGatt gatt;
 private boolean disconnected,scanFailed,finished;
 public static void start(Context context){active=new ServiceLossProbe();active.handler.post(()->active.begin(context));}
 private void fail(Throwable e){finish("FAIL: "+e);}
 private void finish(String message){if(finished)return;finished=true;result=message;if(gatt!=null)gatt.close();}
 private void begin(Context context){try{
  result="RUNNING";
  adapter=context.getSystemService(BluetoothManager.class).getAdapter();
  gatt=adapter.getRemoteDevice("02:00:00:00:00:01").connectGatt(context,false,new BluetoothGattCallback(){
   @Override public void onConnectionStateChange(BluetoothGatt g,int status,int state){try{
    if(state==BluetoothProfile.STATE_CONNECTED&&status==0){
     adapter.getBluetoothLeScanner().startScan(new ScanCallback(){
      @Override public void onScanFailed(int code){if(code!=3)finish("FAIL: wrong scan failure "+code);else{scanFailed=true;check();}}
     });
     result="CONNECTED_WAITING_FOR_SERVICE_LOSS";
    }else if(state==BluetoothProfile.STATE_DISCONNECTED&&status!=0){disconnected=true;check();}
    else finish("FAIL: unexpected connection event "+status+"/"+state);
   }catch(Throwable e){fail(e);}}
  });
  handler.postDelayed(()->{if(!finished)finish("FAIL: no service-loss callbacks");},12000);
 }catch(Throwable e){fail(e);}}
 private void check(){if(!disconnected||!scanFailed||finished)return;try{
  if(adapter.isEnabled()||adapter.getState()!=BluetoothAdapter.STATE_OFF||adapter.getBluetoothLeScanner()!=null)throw new IllegalStateException("adapter still reports available");
  if(gatt.discoverServices())throw new IllegalStateException("operation accepted after service loss");
  finish("PASS: RPC loss disconnects GATT, fails scan, marks adapter off and rejects further operations");
 }catch(Throwable e){fail(e);}}
}
