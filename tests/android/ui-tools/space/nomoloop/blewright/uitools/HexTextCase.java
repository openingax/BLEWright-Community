package space.nomoloop.blewright.uitools;

import android.os.Bundle;
import android.os.SystemClock;
import android.view.accessibility.AccessibilityNodeInfo;
import com.android.uiautomator.core.UiObject;
import com.android.uiautomator.core.UiSelector;
import com.android.uiautomator.testrunner.UiAutomatorTestCase;

/** Standard shell UI test. Only sets the visible Explorer hex field; no BLE access or hooks. */
public final class HexTextCase extends UiAutomatorTestCase {
    private static final class Editor extends UiObject {
        Editor() { super(new UiSelector().packageName("space.nomoloop.blewright.explorer")
            .description("write-hex").className("android.widget.EditText")); }
        AccessibilityNodeInfo node() { return findAccessibilityNodeInfo(3000); }
    }
    public void testRuntimeReady() throws Exception {
        assertNotNull(getUiDevice()); assertTrue(getUiDevice().getDisplayWidth()>0);
        Bundle result=new Bundle();result.putString("result","PASS");getAutomationSupport().sendStatus(0,result);
    }
    public void testSetText() throws Exception {
        String value=getParams().getString("text");
        assertNotNull("Missing test text",value);assertTrue("Input too long",value.length()<=1024);
        Editor editor=new Editor();AccessibilityNodeInfo field=editor.node();
        assertNotNull("Explorer editor not visible",field);assertTrue(field.isEditable());
        Bundle arguments=new Bundle();
        arguments.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,value);
        assertTrue("Text action rejected",field.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT,arguments));
        boolean matched=false;long deadline=SystemClock.uptimeMillis()+3000;
        while(SystemClock.uptimeMillis()<deadline) {
            field=editor.node();
            if(field!=null && !field.isShowingHintText() && value.contentEquals(field.getText()==null ? "" : field.getText())) {matched=true;break;}
            SystemClock.sleep(100);
        }
        assertTrue("Editor did not retain requested text",matched);
        Bundle result=new Bundle();result.putString("result","PASS");result.putInt("length",value.length());
        getAutomationSupport().sendStatus(0,result);
    }
}
