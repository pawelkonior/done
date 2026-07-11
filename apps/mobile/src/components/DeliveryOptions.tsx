import { CalendarClock, CarFront, Check, Truck, Zap } from "lucide-react-native";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";
import { GlassCard } from "@/components/GlassCard";
import { colors, radii, spacing, type } from "@/theme/tokens";
import type { DeliveryOption } from "@/types/domain";

const icons = [Zap, Truck, CarFront];

export function DeliveryOptions({
  options,
  onSelect,
  loadingOptionId,
  disabled = false,
  error,
}: {
  options: DeliveryOption[];
  onSelect?: (optionId: string) => void;
  loadingOptionId?: string | null;
  disabled?: boolean;
  error?: string | null;
}) {
  return (
    <GlassCard style={styles.card}>
      <View style={styles.header}>
        <CalendarClock size={22} color={colors.primaryBright} />
        <View>
          <Text style={styles.title}>Delivery options</Text>
          <Text style={styles.subtitle}>Speed, price and reliability compared</Text>
        </View>
      </View>
      <View style={styles.options} accessibilityRole="radiogroup">
        {options.map((option, index) => {
          const Icon = icons[index] ?? Truck;
          return (
            <Pressable
              key={option.id}
              accessibilityRole="radio"
              accessibilityState={{ checked: option.selected, disabled: disabled || !onSelect }}
              disabled={disabled || !onSelect || Boolean(loadingOptionId)}
              onPress={() => onSelect?.(option.id)}
              style={({ pressed }) => [styles.option, option.selected && styles.optionSelected, disabled && styles.disabled, pressed && styles.pressed]}
              testID={`delivery-option-${option.id}`}
            >
              <View style={[styles.radio, option.selected && styles.radioSelected]}>
                {loadingOptionId === option.id ? <ActivityIndicator size="small" color={colors.text} /> : option.selected ? <Check size={12} color={colors.background} strokeWidth={3} /> : null}
              </View>
              <View style={[styles.optionIcon, option.selected && styles.optionIconSelected]}><Icon size={21} color={colors.primaryBright} /></View>
              <View style={styles.optionText}>
                <View style={styles.nameRow}>
                  <Text style={styles.name}>{option.name}</Text>
                  {option.badge ? <Text style={styles.badge}>{option.badge}</Text> : null}
                </View>
                <Text style={styles.eta}>{option.eta}</Text>
              </View>
              <Text style={styles.price}>{option.price} {option.currency}</Text>
            </Pressable>
          );
        })}
      </View>
      {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
    </GlassCard>
  );
}

const styles = StyleSheet.create({
  card: { padding: spacing.md },
  header: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingHorizontal: spacing.xs, marginBottom: spacing.md },
  title: { ...type.h3, color: colors.text },
  subtitle: { ...type.caption, color: colors.textSecondary },
  options: { gap: spacing.xs },
  option: { minHeight: 72, flexDirection: "row", alignItems: "center", gap: spacing.sm, padding: spacing.sm, borderRadius: radii.md, borderWidth: 1, borderColor: colors.hairline, backgroundColor: "rgba(255,255,255,0.014)" },
  optionSelected: { borderColor: colors.borderStrong, backgroundColor: "rgba(115,69,226,0.10)" },
  radio: { width: 22, height: 22, borderRadius: 11, borderWidth: 2, borderColor: colors.textMuted, alignItems: "center", justifyContent: "center" },
  radioSelected: { backgroundColor: colors.primary, borderColor: colors.primary },
  optionIcon: { width: 42, height: 42, borderRadius: radii.sm, backgroundColor: "rgba(155,92,255,0.07)", alignItems: "center", justifyContent: "center" },
  optionIconSelected: { backgroundColor: "rgba(155,92,255,0.16)" },
  optionText: { flex: 1, minWidth: 0 },
  nameRow: { flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: 6 },
  name: { ...type.bodyMedium, color: colors.text },
  badge: { ...type.caption, color: colors.primaryBright, backgroundColor: "rgba(155,92,255,0.12)", borderRadius: radii.round, paddingHorizontal: 7, paddingVertical: 2 },
  eta: { ...type.caption, color: colors.textSecondary, marginTop: 2 },
  price: { ...type.smallMedium, color: colors.text },
  error: { ...type.caption, color: colors.error, marginTop: spacing.sm, paddingHorizontal: spacing.xs },
  disabled: { opacity: 0.54 },
  pressed: { opacity: 0.72 },
});
