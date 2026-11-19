package space.nomoloop.blewright.explorer;

import android.content.SharedPreferences;

/** Presentation-only predicates; does not change native scan filters or discard results. */
final class ScanFilterState {
    boolean hideUnnamed = true;
    boolean signalEnabled = false;
    int minimumRssi = -75;

    void load(SharedPreferences preferences) {
        hideUnnamed = preferences.getBoolean("hideUnnamed", true);
        signalEnabled = preferences.getBoolean("signalEnabled", false);
        minimumRssi = Math.max(-100, Math.min(-30, preferences.getInt("minimumRssi", -75)));
    }
    void save(SharedPreferences preferences) {
        preferences.edit().putBoolean("hideUnnamed", hideUnnamed).putBoolean("signalEnabled", signalEnabled)
            .putInt("minimumRssi", minimumRssi).apply();
    }
    void reset() { hideUnnamed = true; signalEnabled = false; minimumRssi = -75; }
    boolean matches(String name, int rssi) {
        return (!hideUnnamed || hasName(name)) && (!signalEnabled || (validRssi(rssi) && rssi >= minimumRssi));
    }
    static boolean hasName(String name) { return name != null && name.codePoints().anyMatch(value -> !Character.isWhitespace(value) && !Character.isSpaceChar(value)); }
    // Android ScanResult.getRssi documents the inclusive range [-127, 126].
    static boolean validRssi(int rssi) { return rssi >= -127 && rssi <= 126; }
    String summary() {
        return (hideUnnamed ? "隐藏无名称" : "显示全部名称") + " · " + (signalEnabled ? "≥ " + minimumRssi + " dBm" : "信号不限");
    }
}
