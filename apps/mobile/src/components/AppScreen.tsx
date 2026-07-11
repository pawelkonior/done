import type { PropsWithChildren, ReactNode } from "react";
import { ScrollView, StyleSheet, View, type ScrollViewProps } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { SafeAreaView } from "react-native-safe-area-context";
import { colors, contentMaxWidth, spacing } from "@/theme/tokens";

interface AppScreenProps extends PropsWithChildren {
  scroll?: boolean;
  header?: ReactNode;
  contentStyle?: ScrollViewProps["contentContainerStyle"];
  testID?: string;
}

export function AppScreen({
  children,
  scroll = true,
  header,
  contentStyle,
  testID,
}: AppScreenProps) {
  const content = (
    <View style={styles.shell}>
      {header}
      {children}
    </View>
  );

  return (
    <LinearGradient
      colors={[colors.backgroundDeep, "#0A0A1A", colors.background]}
      locations={[0, 0.45, 1]}
      style={styles.root}
      testID={testID}
    >
      <View pointerEvents="none" style={styles.glowTop} />
      <View pointerEvents="none" style={styles.glowBottom} />
      <SafeAreaView edges={["top"]} style={styles.safe}>
        {scroll ? (
          <ScrollView
            keyboardShouldPersistTaps="handled"
            contentContainerStyle={[styles.scrollContent, contentStyle]}
            showsVerticalScrollIndicator={false}
          >
            {content}
          </ScrollView>
        ) : (
          content
        )}
      </SafeAreaView>
    </LinearGradient>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  safe: { flex: 1 },
  scrollContent: { paddingBottom: 128 },
  shell: {
    width: "100%",
    maxWidth: contentMaxWidth,
    alignSelf: "center",
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
  },
  glowTop: {
    position: "absolute",
    width: 360,
    height: 360,
    borderRadius: 180,
    backgroundColor: "rgba(99, 62, 191, 0.08)",
    top: -180,
    right: -180,
  },
  glowBottom: {
    position: "absolute",
    width: 320,
    height: 320,
    borderRadius: 160,
    backgroundColor: "rgba(65, 96, 215, 0.05)",
    bottom: 80,
    left: -220,
  },
});

