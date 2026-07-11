import type { ReactNode } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { ArrowLeft, MoreHorizontal } from "lucide-react-native";
import { colors, radii, spacing, type } from "@/theme/tokens";

export function PageHeader({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
}) {
  return (
    <View style={styles.header}>
      <View style={styles.textWrap}>
        <Text style={styles.title}>{title}</Text>
        {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}
      </View>
      {action}
    </View>
  );
}

export function DetailHeader({ title, onBack, onMore }: { title: string; onBack: () => void; onMore?: () => void }) {
  return (
    <View style={styles.detailHeader}>
      <Pressable onPress={onBack} style={styles.iconButton} accessibilityLabel="Go back">
        <ArrowLeft size={22} color={colors.text} />
      </Pressable>
      <Text style={styles.detailTitle}>{title}</Text>
      <Pressable onPress={onMore} disabled={!onMore} style={styles.iconButton} accessibilityLabel="More options">
        <MoreHorizontal size={23} color={colors.primaryBright} />
      </Pressable>
    </View>
  );
}

export function CircleAction({ children, onPress, label }: { children: ReactNode; onPress?: () => void; label: string }) {
  return (
    <Pressable onPress={onPress} style={styles.circleAction} accessibilityLabel={label}>
      {children}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  header: { flexDirection: "row", alignItems: "flex-start", justifyContent: "space-between", gap: spacing.md, marginBottom: spacing.xl },
  textWrap: { flex: 1 },
  title: { ...type.h1, color: colors.text },
  subtitle: { ...type.body, color: colors.textSecondary, marginTop: spacing.xs, maxWidth: 360 },
  detailHeader: { minHeight: 56, flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: spacing.xl },
  detailTitle: { ...type.h2, color: colors.text },
  iconButton: { width: 46, height: 46, borderRadius: 23, borderWidth: 1, borderColor: colors.hairline, backgroundColor: "rgba(16,18,33,0.78)", alignItems: "center", justifyContent: "center" },
  circleAction: { width: 52, height: 52, borderRadius: radii.round, borderWidth: 1, borderColor: colors.border, backgroundColor: "rgba(155,92,255,0.06)", alignItems: "center", justifyContent: "center" },
});
