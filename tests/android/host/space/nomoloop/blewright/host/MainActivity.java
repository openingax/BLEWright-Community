package space.nomoloop.blewright.host;
import android.app.Activity;
import android.os.Bundle;
import android.widget.TextView;
/** A standalone host for the public-API probe. No hooks or BLE substitutions in this APK. */
public class MainActivity extends Activity {
 @Override public void onCreate(Bundle state) {
  super.onCreate(state);
  TextView text=new TextView(this);
  text.setText("BLEWright Probe\n\nPublic Android BLE API test host.\nThe external launcher injects the mock and runs the probe.\nSee terminal for PASS / FAIL.");
  text.setTextSize(20);text.setPadding(32,100,32,32);setContentView(text);
 }
}
