import type { TextStyle, ViewStyle } from "react-native";

export const colors = {
  background: "#070914",
  backgroundDeep: "#04050D",
  surface: "#0E1120",
  surfaceSoft: "#121628",
  surfaceElevated: "#171B30",
  primary: "#9B5CFF",
  primaryBright: "#B47BFF",
  primarySoft: "#6F42C1",
  secondary: "#4B7BFF",
  success: "#48D66A",
  warning: "#FFB84D",
  error: "#FF5D73",
  text: "#F7F7FB",
  textSecondary: "#A7AABD",
  textMuted: "#70758B",
  border: "rgba(155, 92, 255, 0.20)",
  borderStrong: "rgba(155, 92, 255, 0.48)",
  hairline: "rgba(186, 190, 221, 0.10)",
  overlay: "rgba(5, 6, 15, 0.82)",
} as const;

export const spacing = {
  xxs: 4,
  xs: 8,
  sm: 12,
  md: 16,
  lg: 20,
  xl: 24,
  xxl: 32,
  xxxl: 40,
} as const;

export const radii = {
  sm: 10,
  md: 16,
  lg: 22,
  xl: 28,
  round: 999,
} as const;

export const shadows = {
  card: {
    shadowColor: "#000000",
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.24,
    shadowRadius: 18,
    elevation: 8,
  } satisfies ViewStyle,
  glow: {
    shadowColor: colors.primary,
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.45,
    shadowRadius: 24,
    elevation: 14,
  } satisfies ViewStyle,
};

export const type = {
  display: { fontSize: 36, lineHeight: 42, fontWeight: "700" } satisfies TextStyle,
  h1: { fontSize: 30, lineHeight: 36, fontWeight: "700" } satisfies TextStyle,
  h2: { fontSize: 23, lineHeight: 29, fontWeight: "700" } satisfies TextStyle,
  h3: { fontSize: 18, lineHeight: 24, fontWeight: "700" } satisfies TextStyle,
  body: { fontSize: 16, lineHeight: 23, fontWeight: "400" } satisfies TextStyle,
  bodyMedium: { fontSize: 16, lineHeight: 23, fontWeight: "600" } satisfies TextStyle,
  small: { fontSize: 14, lineHeight: 20, fontWeight: "400" } satisfies TextStyle,
  smallMedium: { fontSize: 14, lineHeight: 20, fontWeight: "600" } satisfies TextStyle,
  caption: { fontSize: 12, lineHeight: 17, fontWeight: "500" } satisfies TextStyle,
  eyebrow: {
    fontSize: 12,
    lineHeight: 17,
    fontWeight: "600",
    letterSpacing: 1.2,
    textTransform: "uppercase",
  } satisfies TextStyle,
};

export const contentMaxWidth = 520;

