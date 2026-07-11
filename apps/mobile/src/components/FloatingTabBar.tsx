import type { BottomTabBarProps } from "expo-router/build/react-navigation/bottom-tabs";
import { CircleCheck, House, ListTodo, Settings, type LucideIcon } from "lucide-react-native";
import { Platform, Pressable, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { colors, contentMaxWidth, radii, spacing, type } from "@/theme/tokens";

const items: Record<string, { label: string; Icon: LucideIcon }> = {
  index: { label: "Now", Icon: House },
  missions: { label: "Missions", Icon: ListTodo },
  completed: { label: "Completed", Icon: CircleCheck },
  settings: { label: "Settings", Icon: Settings },
};

export function FloatingTabBar({ state, descriptors, navigation }: BottomTabBarProps) {
  const insets = useSafeAreaInsets();
  const visibleRoutes = state.routes.filter((route) => items[route.name]);
  const activeRoute = state.routes[state.index]?.name;
  return (
    <View pointerEvents="box-none" style={styles.outer}>
      <View style={[styles.bar, { paddingBottom: Math.max(insets.bottom, Platform.OS === "web" ? 12 : 8) }]}>
        {visibleRoutes.map((route) => {
          const item = items[route.name]!;
          const focused = activeRoute === route.name || (activeRoute?.startsWith("mission/") && route.name === "missions");
          const onPress = () => {
            const event = navigation.emit({ type: "tabPress", target: route.key, canPreventDefault: true });
            if (!focused && !event.defaultPrevented) navigation.navigate(route.name, route.params);
          };
          return (
            <Pressable
              key={route.key}
              onPress={onPress}
              onLongPress={() => navigation.emit({ type: "tabLongPress", target: route.key })}
              accessibilityRole="button"
              accessibilityState={focused ? { selected: true } : {}}
              accessibilityLabel={descriptors[route.key]?.options.tabBarAccessibilityLabel}
              style={({ pressed }) => [styles.tab, focused && styles.tabActive, pressed && styles.tabPressed]}
              testID={`tab-${route.name}`}
            >
              <item.Icon size={25} strokeWidth={focused ? 2.2 : 1.8} color={focused ? colors.primaryBright : colors.textMuted} />
              <Text style={[styles.label, focused && styles.labelActive]}>{item.label}</Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  outer: { position: "absolute", bottom: 0, left: 0, right: 0, alignItems: "center" },
  bar: {
    width: "100%",
    maxWidth: contentMaxWidth,
    minHeight: 82,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-around",
    paddingTop: spacing.xs,
    paddingHorizontal: spacing.xs,
    borderTopLeftRadius: radii.lg,
    borderTopRightRadius: radii.lg,
    borderWidth: 1,
    borderBottomWidth: 0,
    borderColor: colors.hairline,
    backgroundColor: "rgba(8, 10, 21, 0.97)",
    shadowColor: "#000000",
    shadowOffset: { width: 0, height: -10 },
    shadowOpacity: 0.25,
    shadowRadius: 20,
    elevation: 18,
  },
  tab: { flex: 1, minHeight: 60, maxWidth: 92, borderRadius: radii.md, alignItems: "center", justifyContent: "center", gap: 4 },
  tabActive: { backgroundColor: "rgba(119, 72, 230, 0.12)" },
  tabPressed: { opacity: 0.62 },
  label: { ...type.caption, color: colors.textMuted, fontSize: 10 },
  labelActive: { color: colors.primaryBright },
});
