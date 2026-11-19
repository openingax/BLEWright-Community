package space.nomoloop.blewright.explorer;

/** Behavioral boundary tests without Android runtime or test-framework dependencies. */
public final class FilterPolicyTest {
    static void check(boolean value, String reason) { if (!value) throw new AssertionError(reason); }
    public static void main(String[] args) {
        ScanFilterState filters = new ScanFilterState();
        check(!filters.matches(null,-40), "Null names hidden by default");
        check(!filters.matches("",-40), "Empty names hidden");
        check(!filters.matches(" \t\n",-40), "Whitespace-only names hidden");
        check(!filters.matches("\u3000\u00a0",-40), "Unicode whitespace-only names hidden");
        check(filters.matches("Sensor",-120), "Default does not filter weak named devices");
        check(filters.matches("Sensor",127), "Unknown signal still shown with signal filter off");
        filters.signalEnabled=true; filters.minimumRssi=-70;
        check(filters.matches("Sensor",-70), "Threshold is inclusive");
        check(filters.matches("Sensor",-40), "Stronger negative RSSI accepted");
        check(!filters.matches("Sensor",-71), "Weaker RSSI excluded");
        check(filters.matches("Sensor",126), "Upper native API boundary is valid");
        check(!filters.matches("Sensor",127), "Unknown RSSI sentinel cannot bypass threshold");
        check(!filters.matches(null,-40), "Name and RSSI filters combine with AND");
        filters.hideUnnamed=false;
        check(filters.matches(null,-40), "Name switch restores unnamed broadcasts");
        check(!filters.matches(null,-71), "Disabling name filter preserves signal filter");
        filters.reset();
        check(filters.hideUnnamed && !filters.signalEnabled && filters.minimumRssi==-75, "Reset restores documented defaults");
        System.out.println("PASS: name, whitespace, threshold boundary, stronger/weaker/unknown RSSI, combination and reset");
    }
}
