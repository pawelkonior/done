import { RefreshCw, ShieldCheck } from "lucide-react-native";
import { LinearGradient } from "expo-linear-gradient";
import { StyleSheet, Text, View } from "react-native";
import { colors, radii, spacing, type } from "@/theme/tokens";

export function RecoveryBanner({ recovered, active }: { recovered: number; active?: boolean }) {
  if (!active && recovered < 1) return null;
  return (
    <LinearGradient
      colors={active ? ["rgba(255,184,77,0.17)", "rgba(82,53,16,0.06)"] : ["rgba(72,214,106,0.15)", "rgba(20,78,39,0.04)"]}
      style={[styles.banner, { borderColor: active ? "rgba(255,184,77,0.38)" : "rgba(72,214,106,0.34)" }]}
      testID="recovery-banner"
    >
      <View style={[styles.icon, { backgroundColor: active ? "rgba(255,184,77,0.12)" : "rgba(72,214,106,0.10)" }]}>
        {active ? <RefreshCw size={24} color={colors.warning} /> : <ShieldCheck size={24} color={colors.success} />}
      </View>
      <View style={styles.text}>
        <Text style={styles.title}>{active ? "Self-healing in progress" : `${recovered} failures recovered automatically`}</Text>
        <Text style={styles.subtitle}>
          {active ? "Done is repairing the plan without relaxing your constraints." : "An unavailable product was safely replaced and the declined payment was rerouted."}
        </Text>
      </View>
    </LinearGradient>
  );
}

const styles = StyleSheet.create({
  banner: { flexDirection: "row", alignItems: "center", gap: spacing.md, padding: spacing.md, borderRadius: radii.lg, borderWidth: 1 },
  icon: { width: 48, height: 48, borderRadius: 24, alignItems: "center", justifyContent: "center" },
  text: { flex: 1 },
  title: { ...type.bodyMedium, color: colors.text },
  subtitle: { ...type.caption, color: colors.textSecondary, marginTop: 3 },
});

