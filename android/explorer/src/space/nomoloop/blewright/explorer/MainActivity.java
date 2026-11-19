package space.nomoloop.blewright.explorer;

import android.Manifest;
import android.app.*;
import android.bluetooth.*;
import android.bluetooth.le.*;
import android.content.*;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.StateListDrawable;
import android.graphics.drawable.RippleDrawable;
import android.graphics.drawable.ColorDrawable;
import android.content.res.ColorStateList;
import android.os.Bundle;
import android.view.*;
import android.widget.*;
import java.util.*;

/** An interactive BLE browser; every device operation goes through public Android APIs. */
public final class MainActivity extends Activity {
    private BleClient ble;
    private LinearLayout root, content, navigation;
    private ScrollView scroll;
    private TextView adapterStatus;
    private String page = "scan";
    private AlertDialog writeDialog;
    private BluetoothGatt dialogOwner;
    private boolean drawing;
    private final ScanFilterState filters = new ScanFilterState();
    private SharedPreferences preferences;
    private boolean renderQueued;
    private final Runnable renderUpdate = () -> { renderQueued = false; render(); };
    private static final int INK = Color.rgb(25, 43, 53), TEAL = Color.rgb(0, 112, 105);

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        preferences = getSharedPreferences("scan-filters", MODE_PRIVATE);
        filters.load(preferences);
        ble = new BleClient(this, this::scheduleRender);
        root = column(); root.setBackgroundColor(Color.rgb(244, 247, 248));
        root.setPadding(dp(16), dp(12), dp(16), dp(8));
        setContentView(root);
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            android.graphics.Insets bars = insets.getInsets(WindowInsets.Type.systemBars());
            root.setPadding(dp(16) + bars.left, dp(12) + bars.top, dp(16) + bars.right, dp(8) + bars.bottom);
            return insets;
        });
        root.requestApplyInsets();
        getWindow().getInsetsController().setSystemBarsAppearance(WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS | WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS, WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS | WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS);
        LinearLayout brand = row(); brand.setGravity(Gravity.CENTER_VERTICAL);
        ImageView mark = iconView("bluetooth", Color.WHITE, 28);
        mark.setPadding(dp(8), dp(8), dp(8), dp(8)); mark.setBackground(shape(TEAL));
        brand.addView(mark, new LinearLayout.LayoutParams(dp(44), dp(44)));
        LinearLayout titles = column(); titles.setPadding(dp(12), 0, 0, 0);
        TextView title = text("BLEExplorer", 23, INK); title.setTypeface(null, Typeface.BOLD); titles.addView(title);
        titles.addView(text("探索附近的蓝牙设备", 12, Color.rgb(102, 121, 128)));
        brand.addView(titles, new LinearLayout.LayoutParams(0, -2, 1)); root.addView(brand);
        adapterStatus = text("", 12, TEAL); adapterStatus.setPadding(dp(2), dp(10), 0, dp(10)); root.addView(adapterStatus);
        scroll = new ScrollView(this); scroll.setFillViewport(true); scroll.setClipToPadding(false);
        scroll.setPadding(0, 0, 0, dp(12));
        content = column(); scroll.addView(content);
        root.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));
        navigation = row(); navigation.setPadding(dp(4), dp(6), dp(4), dp(4));
        navigation.setBackground(shape(Color.WHITE)); root.addView(navigation);
        render();
    }
    @Override public void onResume() { super.onResume(); if (ble != null) ble.resume(); }
    @Override public void onStop() { if (ble != null) ble.pause(); super.onStop(); }
    @Override public void onDestroy() {
        if (writeDialog != null) writeDialog.dismiss();
        if (ble != null) { ble.pause(); ble.main.removeCallbacks(renderUpdate); }
        super.onDestroy();
    }
    @Override public void onRequestPermissionsResult(int request, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(request, permissions, results);
        ble.refresh(); render();
    }
    @Override public void onBackPressed() {
        if (!page.equals("scan")) { switchPage("scan"); return; }
        if (ble.gatt != null) {
            AlertDialog dialog = new AlertDialog.Builder(this).setTitle("断开并退出？").setIcon(new ExplorerIcon("unlink",TEAL,dp(24)))
                .setMessage("退出会关闭当前连接和通知订阅。")
                .setNegativeButton("取消", null).setPositiveButton("退出", (d, w) -> finish()).create();
            dialog.setOnShowListener(d -> decorateDialog(dialog)); dialog.show();
        } else super.onBackPressed();
    }
    private void scheduleRender() {
        if (renderQueued || isDestroyed()) return;
        renderQueued = true;
        ble.main.postDelayed(renderUpdate, 150);
    }
    private void switchPage(String next) { page = next; scroll.scrollTo(0, 0); render(); }
    private void render() {
        if (root == null || drawing || isDestroyed()) return;
        drawing = true;
        try {
            if (writeDialog != null && ble.gatt != dialogOwner) writeDialog.dismiss();
            adapterStatus.setText(ble.availability);
            adapterStatus.setCompoundDrawablePadding(dp(6));
            adapterStatus.setCompoundDrawables(new ExplorerIcon(ble.usable() ? "check" : "info", ble.usable() ? TEAL : Color.rgb(178,105,36), dp(16)), null, null, null);
            adapterStatus.setContentDescription("adapter-status: " + ble.availability);
            navigation.removeAllViews();
            tab("附近设备", "scan"); tab("设备详情", "detail"); tab("操作日志", "logs");
            int offset = scroll.getScrollY();
            content.removeAllViews();
            if (page.equals("scan")) renderScan();
            else if (page.equals("detail")) renderDetail();
            else renderLogs();
            scroll.post(() -> scroll.scrollTo(0, offset));
        } finally { drawing = false; }
    }
    private void tab(String title, String target) {
        Button button = button(title, "tab-" + target, () -> switchPage(target));
        boolean selected = page.equals(target);
        button.setTextColor(selected ? TEAL : Color.rgb(111, 129, 136));
        button.setTextSize(11);
        button.setBackground(shape(selected ? Color.rgb(225, 243, 238) : Color.WHITE));
        button.setCompoundDrawables(null, new ExplorerIcon(iconFor("tab-" + target), selected ? TEAL : Color.rgb(111,129,136), dp(22)), null, null);
        button.setCompoundDrawablePadding(dp(4)); button.setPadding(dp(4),dp(8),dp(4),dp(6));
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(0, dp(66), 1); params.setMargins(dp(3),0,dp(3),0);
        navigation.addView(button, params);
    }
    private void renderScan() {
        LinearLayout status = card();
        heading(status, "radar", "附近设备", 21);
        TextView scanLabel = label(status, ble.scanState, 14); scanLabel.setContentDescription("scan-status: " + ble.scanState);
        if (!ble.permitted()) {
            label(status, "扫描与连接需要“附近设备”权限。拒绝后可重新授权；若系统不再弹窗，请在应用设置中开启。", 14);
            status.addView(button("授权附近设备", "grant-permissions", () -> requestPermissions(new String[]{Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT}, 1)));
            status.addView(button("应用权限设置", "permission-settings", () -> startActivity(new Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS, android.net.Uri.parse("package:" + getPackageName())))));
        } else if (!ble.usable()) {
            status.addView(button("请求开启蓝牙", "enable-bluetooth", () -> {
                try { startActivity(new Intent(BluetoothAdapter.ACTION_REQUEST_ENABLE)); }
                catch (RuntimeException e) { ble.log("无法开启蓝牙：" + BleClient.error(e)); render(); }
            }));
        }
        Button scan = button(ble.scanCallback == null ? "开始扫描" : "停止扫描", "scan-toggle", () -> {
            if (ble.scanCallback == null) ble.startScan(); else ble.stopScan("扫描已手动停止");
        });
        scan.setEnabled(ble.usable() && ble.gatt == null); status.addView(scan);
        if (ble.gatt != null) label(status, "当前已有连接。请在设备详情中断开后再扫描。", 13);
        content.addView(status);
        LinearLayout filterCard = card();
        LinearLayout filterRow = row(); filterRow.setGravity(Gravity.CENTER_VERTICAL);
        LinearLayout explanation = column();
        heading(explanation, "filter", "设备筛选", 15);
        TextView summary = label(explanation, filters.summary(), 12);
        summary.setContentDescription("filter-summary: " + filters.summary());
        filterRow.addView(explanation, new LinearLayout.LayoutParams(0,-2,1));
        Button editFilters = button("筛选", "edit-filters", this::showFilters);
        filterRow.addView(editFilters, new LinearLayout.LayoutParams(dp(86), dp(44)));
        filterCard.addView(filterRow); content.addView(filterCard);
        ArrayList<ScanResult> visible = new ArrayList<>();
        for (ScanResult result : ble.devices.values()) {
            String name = result.getScanRecord() == null ? null : result.getScanRecord().getDeviceName();
            if (filters.matches(name, result.getRssi())) visible.add(result);
        }
        TextView count = label(content, "显示 " + visible.size() + " / 已发现 " + ble.devices.size(), 13);
        count.setContentDescription("device-count: " + visible.size() + "/" + ble.devices.size());
        if (visible.isEmpty()) {
            LinearLayout empty = card();
            heading(empty, ble.devices.isEmpty() ? "radar" : "filter", ble.devices.isEmpty() ? "等待设备广播" : "没有符合条件的设备", 18);
            label(empty, ble.devices.isEmpty() ? "开始扫描后，附近设备会显示在这里。" : "已收到 " + ble.devices.size() + " 台设备的广播。可放宽信号下限，或显示无名称设备。", 13);
            if (!ble.devices.isEmpty()) empty.addView(button("显示所有设备", "show-all-devices", () -> {
                filters.hideUnnamed = false; filters.signalEnabled = false; filters.save(preferences); render();
            }));
            content.addView(empty);
        }
        for (ScanResult result : visible) {
            LinearLayout device = card();
            LinearLayout top = row(); top.setGravity(Gravity.CENTER_VERTICAL);
            ImageView mark = iconView("bluetooth", TEAL, 23);
            mark.setPadding(dp(7),dp(7),dp(7),dp(7)); mark.setBackground(shape(Color.rgb(229,243,239)));
            top.addView(mark, new LinearLayout.LayoutParams(dp(38), dp(38)));
            LinearLayout identity = column(); identity.setPadding(dp(10),0,dp(4),0);
            TextView name = label(identity, BleClient.name(result), 16); name.setTypeface(null,Typeface.BOLD);
            name.setMaxLines(2); name.setEllipsize(android.text.TextUtils.TruncateAt.END);
            TextView address = label(identity, result.getDevice().getAddress(), 11); address.setTextColor(Color.rgb(106,123,131));
            top.addView(identity, new LinearLayout.LayoutParams(0,-2,1));
            int rssi = result.getRssi();
            int signalColor = rssi >= -65 ? TEAL : rssi >= -85 ? Color.rgb(153,106,38) : Color.rgb(142,113,110);
            TextView signal = text(ScanFilterState.validRssi(rssi) ? rssi + " dBm" : "信号未知", 11, signalColor);
            signal.setCompoundDrawables(null,new ExplorerIcon("signal",signalColor,dp(20)),null,null); signal.setGravity(Gravity.CENTER);
            top.addView(signal, new LinearLayout.LayoutParams(dp(64),-2)); device.addView(top);
            LinearLayout actions = row(); actions.setPadding(0,dp(10),0,0);
            Button advertisement = button("广播详情", "advertisement-" + result.getDevice().getAddress(), () -> showAdvertisement(result));
            actions.addView(advertisement, actionParams());
            Button connect = button("连接设备", "connect-" + result.getDevice().getAddress(), () -> { page = "detail"; scroll.scrollTo(0, 0); ble.connect(result); render(); });
            connect.setEnabled(ble.usable() && ble.gatt == null); actions.addView(connect, actionParams());
            device.addView(actions); content.addView(device);
        }
    }
    private void showFilters() {
        LinearLayout form = column(); form.setPadding(dp(20),dp(8),dp(20),dp(8));
        Switch named = new Switch(this); named.setText("隐藏无名称设备"); named.setTextSize(15); named.setChecked(filters.hideUnnamed);
        named.setContentDescription("filter-named"); named.setPadding(0,dp(12),0,dp(16)); form.addView(named);
        Switch signal = new Switch(this); signal.setText("按信号强度筛选"); signal.setTextSize(15); signal.setChecked(filters.signalEnabled);
        signal.setContentDescription("filter-signal"); signal.setPadding(0,dp(8),0,dp(12)); form.addView(signal);
        TextView threshold = label(form, "", 16); threshold.setContentDescription("filter-threshold");
        SeekBar slider = new SeekBar(this); slider.setMin(-100); slider.setMax(-30); slider.setProgress(filters.minimumRssi);
        slider.setContentDescription("filter-rssi-slider"); slider.setProgressTintList(ColorStateList.valueOf(TEAL)); slider.setThumbTintList(ColorStateList.valueOf(TEAL));
        form.addView(slider, new LinearLayout.LayoutParams(-1,dp(48)));
        TextView range = label(form, "较远  −100 dBm                         −30 dBm  较近", 11); range.setTextColor(Color.GRAY);
        LinearLayout presets = row();
        for (int value : new int[]{-85,-70,-55}) {
            Button preset = button("≥ " + value, "rssi-preset-" + (-value), () -> { signal.setChecked(true); slider.setProgress(value); });
            preset.setCompoundDrawables(null,null,null,null); presets.addView(preset, actionParams());
        }
        form.addView(presets);
        label(form, "数值越接近 0，信号通常越强。开启后仅显示达到下限的设备；实际距离还受遮挡和发射功率影响。", 12);
        Runnable update = () -> {
            slider.setEnabled(signal.isChecked());
            threshold.setText(signal.isChecked() ? "信号下限 ≥ " + slider.getProgress() + " dBm" : "信号不限");
            threshold.setTextColor(signal.isChecked() ? TEAL : Color.GRAY);
        };
        signal.setOnCheckedChangeListener((view,checked) -> update.run());
        slider.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            public void onProgressChanged(SeekBar view,int progress,boolean fromUser) { update.run(); }
            public void onStartTrackingTouch(SeekBar view) {}
            public void onStopTrackingTouch(SeekBar view) {}
        });
        update.run();
        ScrollView body = new ScrollView(this); body.addView(form);
        AlertDialog dialog = new AlertDialog.Builder(this).setTitle("筛选设备").setIcon(new ExplorerIcon("filter",TEAL,dp(24)))
            .setView(body).setNegativeButton("取消",null)
            .setNeutralButton("恢复默认",(d,w) -> { filters.reset(); filters.save(preferences); render(); })
            .setPositiveButton("应用",(d,w) -> { filters.hideUnnamed=named.isChecked(); filters.signalEnabled=signal.isChecked();
                filters.minimumRssi=slider.getProgress(); filters.save(preferences); render(); }).create();
        dialog.setOnShowListener(d -> {
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setContentDescription("apply-filters");
            dialog.getButton(AlertDialog.BUTTON_NEUTRAL).setContentDescription("reset-filters");
            decorateDialog(dialog);
        });
        dialog.show();
    }
    private void showAdvertisement(ScanResult result) {
        ScanRecord record = result.getScanRecord();
        String information = result.getDevice().getAddress() + "\n" + result.getRssi() + " dBm\n\n服务 UUID\n"
            + (record == null || record.getServiceUuids() == null ? "未广播服务 UUID" : record.getServiceUuids().toString())
            + "\n\n广播数据 · HEX\n" + (record == null ? "无广播记录" : BleClient.hex(record.getBytes()));
        TextView body = text(information,13,INK); body.setPadding(dp(24),dp(12),dp(24),dp(16));
        body.setTypeface(Typeface.MONOSPACE); body.setTextIsSelectable(true); body.setContentDescription("advertisement-details");
        ScrollView scroll = new ScrollView(this); scroll.addView(body);
        AlertDialog dialog = new AlertDialog.Builder(this).setTitle(BleClient.name(result)).setIcon(new ExplorerIcon("info",TEAL,dp(24)))
            .setView(scroll).setPositiveButton("完成",null).create();
        dialog.setOnShowListener(d -> decorateDialog(dialog)); dialog.show();
    }
    private void renderDetail() {
        LinearLayout summary = card();
        heading(summary, "bluetooth", ble.selected == null ? "尚未选择设备" : "设备连接", 20);
        if (ble.selected != null) label(summary, ble.selected.getAddress(), 14);
        TextView state = label(summary, ble.state, 15); state.setContentDescription("connection-status: " + ble.state);
        if (ble.pending != null) label(summary, ble.pending + "进行中…", 13);
        if (ble.gatt != null) {
            summary.addView(button(ble.ready ? "断开连接" : "取消连接", "disconnect", () -> ble.release("已主动断开")));
        } else if (ble.selected != null && ble.devices.containsKey(ble.selected.getAddress())) {
            Button reconnect = button("重新连接", "reconnect", () -> ble.connect(ble.devices.get(ble.selected.getAddress())));
            reconnect.setEnabled(ble.usable()); summary.addView(reconnect);
        } else label(summary, "在附近设备页扫描并选择设备。", 14);
        content.addView(summary);
        for (BluetoothGattService service : ble.services) {
            heading(content, "layers", service.getType() == 0 ? "主服务" : "次级服务", 14);
            TextView uuid = label(content, service.getUuid().toString(), 13); uuid.setTypeface(Typeface.MONOSPACE);
            for (BluetoothGattCharacteristic c : service.getCharacteristics()) renderCharacteristic(c);
        }
        if (ble.ready && ble.services.isEmpty()) label(content, "服务发现已完成，设备未返回服务。", 15);
    }
    private void renderCharacteristic(BluetoothGattCharacteristic c) {
        LinearLayout card = card();
        heading(card, "layers", "特征值", 13);
        TextView uuid = label(card, c.getUuid().toString(), 14); uuid.setTypeface(Typeface.MONOSPACE);
        int properties = c.getProperties();
        ArrayList<String> names = new ArrayList<>();
        if ((properties & 2) != 0) names.add("读取");
        if ((properties & 8) != 0) names.add("有响应写入");
        if ((properties & 4) != 0) names.add("无响应写入");
        if ((properties & 16) != 0) names.add("通知");
        if ((properties & 32) != 0) names.add("指示");
        label(card, names.isEmpty() ? "无可用基础操作" : String.join(" · ", names), 12);
        byte[] value = ble.values.get(c);
        TextView display = label(card, value == null ? "尚未读取或收到通知" : "HEX  " + BleClient.hex(value) + "\nUTF-8  " + BleClient.utf8(value), 14);
        display.setContentDescription("characteristic-value: " + (value == null ? "empty" : BleClient.hex(value)));
        display.setTextIsSelectable(true);
        LinearLayout actions = row();
        if ((properties & 2) != 0) addAction(actions, "读取", "read", () -> ble.read(c));
        if ((properties & (8 | 4)) != 0) addAction(actions, "写入", "write", () -> showWrite(c));
        if ((properties & (16 | 32)) != 0) addAction(actions, ble.subscriptions.contains(c) ? "取消订阅" : "订阅", "subscribe", () -> ble.subscribe(c));
        card.addView(actions);
        if ((properties & (16 | 32)) != 0) {
            TextView subscription = label(card, ble.subscriptions.contains(c) ? "通知已订阅" : "通知未订阅", 12);
            subscription.setContentDescription("subscription-status: " + (ble.subscriptions.contains(c) ? "on" : "off"));
        }
        for (BluetoothGattDescriptor descriptor : c.getDescriptors()) label(card, "描述符  " + descriptor.getUuid(), 11);
        content.addView(card);
    }
    private void addAction(LinearLayout parent, String title, String id, Runnable action) {
        Button button = button(title, id, action); button.setEnabled(ble.canOperate());
        // Keep the four-character unsubscribe label legible on narrower phones as well.
        button.setTextSize(12); button.setSingleLine(true);
        button.setPadding(dp(4), dp(4), dp(4), dp(4)); button.setCompoundDrawablePadding(dp(4));
        parent.addView(button, actionParams());
    }
    private void showWrite(BluetoothGattCharacteristic c) {
        if (!ble.canOperate()) return;
        dialogOwner = ble.gatt;
        LinearLayout form = column(); form.setPadding(dp(24), dp(8), dp(24), 0);
        label(form, "输入十六进制字节，例如 01 02 FF。实际长度限制取决于设备和当前 MTU。", 14);
        EditText input = new EditText(this);
        // Hex bytes are ASCII text, not natural language: avoid IME composition/autocorrection.
        input.setInputType(android.text.InputType.TYPE_CLASS_TEXT | android.text.InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
            | android.text.InputType.TYPE_TEXT_FLAG_MULTI_LINE);
        input.setImeOptions(android.view.inputmethod.EditorInfo.IME_FLAG_FORCE_ASCII
            | android.view.inputmethod.EditorInfo.IME_FLAG_NO_PERSONALIZED_LEARNING);
        input.setImeHintLocales(new android.os.LocaleList(Locale.ENGLISH));
        input.setTypeface(Typeface.MONOSPACE);
        input.setHint("01 02 FF"); input.setContentDescription("write-hex"); form.addView(input);
        boolean withResponse = (c.getProperties() & BluetoothGattCharacteristic.PROPERTY_WRITE) != 0;
        boolean withoutResponse = (c.getProperties() & BluetoothGattCharacteristic.PROPERTY_WRITE_NO_RESPONSE) != 0;
        CheckBox noResponse = new CheckBox(this); noResponse.setText("无响应写入（不确认外设接收）");
        noResponse.setChecked(!withResponse); noResponse.setEnabled(withResponse && withoutResponse);
        if (withoutResponse) form.addView(noResponse);
        writeDialog = new AlertDialog.Builder(this).setTitle("写入特征值").setIcon(new ExplorerIcon("write",TEAL,dp(24))).setView(form)
            .setNegativeButton("取消", null).setPositiveButton("发送", null).create();
        writeDialog.setOnDismissListener(d -> { writeDialog = null; dialogOwner = null; });
        writeDialog.setOnShowListener(d -> {
            decorateDialog(writeDialog);
            Button send = writeDialog.getButton(AlertDialog.BUTTON_POSITIVE); send.setContentDescription("send-write");
            send.setOnClickListener(v -> {
                try {
                    byte[] bytes = BleClient.parseHex(input.getText().toString());
                    if (!ble.canOperate() || ble.gatt != dialogOwner) { input.setError("连接已变化，请关闭后重试"); return; }
                    ble.write(c, bytes, noResponse.isChecked() ? BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE : BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT);
                    if (writeDialog != null) writeDialog.dismiss();
                } catch (IllegalArgumentException e) { input.setError(e.getMessage()); }
            });
        });
        writeDialog.show();
    }
    private void renderLogs() {
        LinearLayout header = card(); heading(header, "logs", "操作日志", 21);
        label(header, "最近 300 条记录 · 最新消息在前", 13);
        LinearLayout actions = row();
        actions.addView(button("复制日志", "copy-logs", () -> {
            getSystemService(android.content.ClipboardManager.class).setPrimaryClip(ClipData.newPlainText("BLEExplorer", String.join("\n", ble.logs)));
            Toast.makeText(this, "日志已复制", Toast.LENGTH_SHORT).show();
        }), actionParams());
        actions.addView(button("清空日志", "clear-logs", () -> { ble.logs.clear(); render(); }), actionParams());
        header.addView(actions); content.addView(header);
        StringBuilder recent = new StringBuilder();
        for (int i = ble.logs.size() - 1; i >= 0; i--) recent.append(ble.logs.get(i)).append("\n\n");
        TextView log = label(content, recent.length() == 0 ? "暂无操作记录" : recent.toString(), 12);
        log.setTypeface(Typeface.MONOSPACE); log.setTextIsSelectable(true); log.setContentDescription("operation-log");
    }
    private int dp(int value) { return Math.round(getResources().getDisplayMetrics().density * value); }
    private LinearLayout column() { LinearLayout view = new LinearLayout(this); view.setOrientation(LinearLayout.VERTICAL); return view; }
    private LinearLayout row() { LinearLayout view = new LinearLayout(this); view.setOrientation(LinearLayout.HORIZONTAL); return view; }
    private TextView text(String value, int size, int color) {
        TextView view = new TextView(this); view.setText(value); view.setTextSize(size); view.setTextColor(color); view.setPadding(0, dp(4), 0, dp(6)); return view;
    }
    private TextView label(LinearLayout parent, String value, int size) { TextView view = text(value, size, INK); parent.addView(view); return view; }
    private Button button(String title, String id, Runnable action) {
        Button view = new Button(this); view.setText(title); view.setTextSize(13); view.setTextColor(TEAL); view.setAllCaps(false);
        view.setContentDescription(id); view.setMinWidth(0); view.setMinimumWidth(0); view.setPadding(dp(12), dp(5), dp(12), dp(5));
        view.setMinHeight(dp(44));
        view.setCompoundDrawablePadding(dp(6));
        view.setCompoundDrawables(new ExplorerIcon(iconFor(id),TEAL,dp(18)),null,null,null);
        StateListDrawable background = new StateListDrawable();
        background.addState(new int[]{-android.R.attr.state_enabled}, shape(Color.rgb(237, 240, 241)));
        background.addState(new int[]{android.R.attr.state_pressed}, shape(Color.rgb(190, 219, 215)));
        background.addState(new int[]{}, shape(Color.rgb(224, 240, 237)));
        view.setBackground(new RippleDrawable(ColorStateList.valueOf(Color.rgb(185,216,207)),background,shape(Color.WHITE)));
        view.setTextColor(new ColorStateList(new int[][]{new int[]{-android.R.attr.state_enabled}, new int[]{}}, new int[]{Color.rgb(142, 153, 157), TEAL}));
        view.setStateListAnimator(null); view.setElevation(0);
        if (id.equals("scan-toggle")) {
            view.setCompoundDrawables(new ExplorerIcon(ble.scanCallback == null ? "radar" : "stop", TEAL, dp(18)),null,null,null);
        } else if (id.equals("subscribe")) {
            view.setCompoundDrawables(new ExplorerIcon(title.equals("取消订阅") ? "bell-off" : "bell",TEAL,dp(18)),null,null,null);
        }
        view.setOnClickListener(v -> action.run()); return view;
    }
    private String iconFor(String id) {
        if (id.startsWith("connect-") || id.equals("reconnect")) return "link";
        if (id.startsWith("advertisement-")) return "info";
        switch (id) {
            case "tab-scan": return "radar";
            case "tab-detail": case "enable-bluetooth": return "bluetooth";
            case "tab-logs": return "logs";
            case "edit-filters": return "filter";
            case "show-all-devices": return "refresh";
            case "disconnect": return "unlink";
            case "read": return "read";
            case "write": return "write";
            case "subscribe": return "bell";
            case "copy-logs": return "copy";
            case "clear-logs": return "trash";
            case "grant-permissions": return "shield";
            case "permission-settings": return "settings";
            default: return "signal";
        }
    }
    private ImageView iconView(String name, int color, int size) {
        ImageView view = new ImageView(this); view.setImageDrawable(new ExplorerIcon(name,color,dp(size))); return view;
    }
    private void heading(LinearLayout parent, String icon, String title, int size) {
        TextView view = text(title,size,INK); view.setTypeface(null,Typeface.BOLD);
        view.setCompoundDrawablePadding(dp(8)); view.setCompoundDrawables(new ExplorerIcon(icon,TEAL,dp(20)),null,null,null); parent.addView(view);
    }
    private LinearLayout.LayoutParams actionParams() {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(0,dp(44),1);
        params.setMargins(dp(3),dp(3),dp(3),dp(3)); return params;
    }
    private void decorateDialog(AlertDialog dialog) {
        if (dialog.getWindow() != null) {
            GradientDrawable background = shape(Color.WHITE); background.setCornerRadius(dp(20));
            dialog.getWindow().setBackgroundDrawable(background);
        }
        for (int which : new int[]{AlertDialog.BUTTON_POSITIVE, AlertDialog.BUTTON_NEGATIVE, AlertDialog.BUTTON_NEUTRAL}) {
            Button button = dialog.getButton(which);
            if (button == null) continue;
            String icon = which == AlertDialog.BUTTON_NEGATIVE ? "close" : which == AlertDialog.BUTTON_NEUTRAL ? "refresh" : "check";
            button.setTextColor(TEAL); button.setCompoundDrawablePadding(dp(6));
            button.setCompoundDrawables(new ExplorerIcon(icon,TEAL,dp(16)),null,null,null);
        }
    }
    private GradientDrawable shape(int color) {
        GradientDrawable shape = new GradientDrawable(); shape.setColor(color); shape.setCornerRadius(dp(8)); return shape;
    }
    private LinearLayout card() {
        LinearLayout card = column(); card.setPadding(dp(16), dp(12), dp(16), dp(12));
        GradientDrawable background = new GradientDrawable(); background.setColor(Color.WHITE); background.setCornerRadius(dp(16));
        background.setStroke(dp(1), Color.rgb(222, 232, 233)); card.setBackground(background);
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2); params.setMargins(0, dp(8), 0, dp(8)); card.setLayoutParams(params);
        return card;
    }
}
