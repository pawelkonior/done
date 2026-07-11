import { CheckCircle2, ShoppingBasket } from "lucide-react-native";
import { StyleSheet, Text, View } from "react-native";
import { GlassCard } from "@/components/GlassCard";
import { colors, radii, spacing, type } from "@/theme/tokens";
import type { Basket } from "@/types/domain";

export function BasketCard({ basket }: { basket: Basket }) {
  return (
    <GlassCard style={styles.card}>
      <View style={styles.header}>
        <View style={styles.headerIcon}><ShoppingBasket size={22} color={colors.primaryBright} /></View>
        <View style={styles.headerText}>
          <Text style={styles.title}>Optimized basket</Text>
          <Text style={styles.subtitle}>{basket.items.length} items · {basket.merchant}</Text>
        </View>
        <View style={styles.safe}><CheckCircle2 size={15} color={colors.success} /><Text style={styles.safeText}>Safe</Text></View>
      </View>
      <View style={styles.items}>
        {basket.items.map((item) => (
          <View key={item.id} style={styles.item}>
            <View style={styles.quantity}><Text style={styles.quantityText}>{item.quantity}×</Text></View>
            <View style={styles.itemText}>
              <Text style={styles.itemName}>{item.name}</Text>
              <Text style={styles.itemMeta}>{item.category}{item.nut_free ? " · nut-free" : ""}</Text>
              {item.replaced_item ? <Text style={styles.replaced}>Replaced {item.replaced_item}</Text> : null}
            </View>
            <Text style={styles.itemPrice}>{item.total.toFixed(0)} {basket.currency}</Text>
          </View>
        ))}
      </View>
      <View style={styles.totalRows}>
        <View style={styles.totalRow}><Text style={styles.totalLabel}>Subtotal</Text><Text style={styles.totalValue}>{basket.subtotal.toFixed(0)} {basket.currency}</Text></View>
        <View style={styles.totalRow}><Text style={styles.totalLabel}>Delivery</Text><Text style={styles.totalValue}>{basket.delivery_cost.toFixed(0)} {basket.currency}</Text></View>
        <View style={[styles.totalRow, styles.finalRow]}><Text style={styles.finalLabel}>Total</Text><Text style={styles.finalValue}>{basket.total.toFixed(0)} {basket.currency}</Text></View>
      </View>
    </GlassCard>
  );
}

const styles = StyleSheet.create({
  card: { padding: spacing.md },
  header: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  headerIcon: { width: 44, height: 44, borderRadius: radii.md, backgroundColor: "rgba(155,92,255,0.10)", alignItems: "center", justifyContent: "center" },
  headerText: { flex: 1 },
  title: { ...type.h3, color: colors.text },
  subtitle: { ...type.caption, color: colors.textSecondary },
  safe: { flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: "rgba(72,214,106,0.08)", paddingVertical: 5, paddingHorizontal: 8, borderRadius: radii.round },
  safeText: { ...type.caption, color: colors.success },
  items: { marginTop: spacing.md, borderTopWidth: 1, borderColor: colors.hairline },
  item: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingVertical: spacing.sm, borderBottomWidth: 1, borderBottomColor: colors.hairline },
  quantity: { width: 32, height: 32, borderRadius: 10, alignItems: "center", justifyContent: "center", backgroundColor: "rgba(255,255,255,0.035)" },
  quantityText: { ...type.caption, color: colors.primaryBright },
  itemText: { flex: 1 },
  itemName: { ...type.smallMedium, color: colors.text },
  itemMeta: { ...type.caption, color: colors.textMuted },
  replaced: { ...type.caption, color: colors.warning, marginTop: 2 },
  itemPrice: { ...type.smallMedium, color: colors.text },
  totalRows: { paddingTop: spacing.sm, gap: 7 },
  totalRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  totalLabel: { ...type.small, color: colors.textSecondary },
  totalValue: { ...type.smallMedium, color: colors.text },
  finalRow: { paddingTop: spacing.sm, marginTop: 3, borderTopWidth: 1, borderTopColor: colors.hairline },
  finalLabel: { ...type.bodyMedium, color: colors.text },
  finalValue: { ...type.h3, color: colors.text },
});

