import {
  CakeSlice,
  Coffee,
  Laptop,
  Package,
  ShoppingCart,
  type LucideIcon,
} from "lucide-react-native";
import { LinearGradient } from "expo-linear-gradient";
import { StyleSheet, View } from "react-native";
import { colors, radii } from "@/theme/tokens";
import type { MissionSummary } from "@/types/domain";

type IconName = NonNullable<MissionSummary["icon"]>;
type Accent = NonNullable<MissionSummary["accent"]>;

const icons: Record<IconName, LucideIcon> = {
  cake: CakeSlice,
  laptop: Laptop,
  cart: ShoppingCart,
  coffee: Coffee,
  package: Package,
};

export const accentColors: Record<Accent, string> = {
  violet: colors.primary,
  blue: colors.secondary,
  green: colors.success,
  amber: "#F1A45C",
};

export function IconTile({
  icon = "cake",
  accent = "violet",
  size = 60,
}: {
  icon?: IconName;
  accent?: Accent;
  size?: number;
}) {
  const Icon = icons[icon];
  const color = accentColors[accent];
  return (
    <LinearGradient
      colors={[`${color}42`, `${color}13`]}
      style={[
        styles.tile,
        {
          width: size,
          height: size,
          borderRadius: Math.max(radii.md, size * 0.25),
          borderColor: `${color}45`,
        },
      ]}
    >
      <View style={styles.inner}>
        <Icon color={color} size={Math.round(size * 0.48)} strokeWidth={1.8} />
      </View>
    </LinearGradient>
  );
}

const styles = StyleSheet.create({
  tile: { alignItems: "center", justifyContent: "center", borderWidth: 1 },
  inner: { alignItems: "center", justifyContent: "center" },
});

