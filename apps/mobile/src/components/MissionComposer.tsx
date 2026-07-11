import { useEffect, useState } from "react";
import { KeyboardAvoidingView, Modal, Platform, Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { X } from "lucide-react-native";
import { LinearGradient } from "expo-linear-gradient";
import { colors, radii, spacing, type } from "@/theme/tokens";

export function MissionComposer({
  visible,
  loading,
  onClose,
  onSubmit,
  mode = "create",
  initialValue,
  error,
}: {
  visible: boolean;
  loading: boolean;
  onClose: () => void;
  onSubmit: (transcript: string) => Promise<void> | void;
  mode?: "create" | "correction";
  initialValue?: string;
  error?: string | null;
}) {
  const [text, setText] = useState(initialValue ?? "");
  useEffect(() => {
    if (visible) setText(initialValue ?? "");
  }, [initialValue, mode, visible]);
  const correcting = mode === "correction";
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={styles.backdrop}>
        <Pressable style={StyleSheet.absoluteFill} onPress={onClose} />
        <LinearGradient colors={["#17192C", "#0A0C19"]} style={styles.sheet}>
          <View style={styles.handle} />
          <View style={styles.titleRow}>
            <View>
              <Text style={styles.title}>{correcting ? "Correct this mission" : "Add a mission"}</Text>
              <Text style={styles.subtitle}>{correcting ? "Describe only what should change." : "Tell Done the outcome you want."}</Text>
            </View>
            <Pressable onPress={onClose} style={styles.close} accessibilityLabel="Close">
              <X color={colors.textSecondary} size={22} />
            </Pressable>
          </View>
          <TextInput
            multiline
            value={text}
            onChangeText={setText}
            placeholder={correcting ? "For example: Increase the budget to 350 PLN…" : "Describe your mission…"}
            placeholderTextColor={colors.textMuted}
            style={styles.input}
            autoFocus
            testID="mission-input"
          />
          <View style={styles.hintRow}>
            <Text style={styles.hint}>{correcting ? "Unchanged constraints stay locked and the contract receives a new version." : "Done will preserve budget, deadline and safety constraints."}</Text>
          </View>
          {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
          <Pressable
            accessibilityRole="button"
            disabled={loading || text.trim().length < 5}
            onPress={() => void onSubmit(text.trim())}
            style={({ pressed }) => [styles.buttonWrap, pressed && styles.buttonPressed]}
            testID="create-mission-button"
          >
            <LinearGradient colors={[colors.primary, "#7443EA"]} style={styles.button}>
              <Text style={styles.buttonText}>{loading ? (correcting ? "Updating mission…" : "Creating mission…") : (correcting ? "Apply correction" : "Consider it done")}</Text>
            </LinearGradient>
          </Pressable>
        </LinearGradient>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: colors.overlay, justifyContent: "flex-end" },
  sheet: {
    width: "100%",
    maxWidth: 520,
    alignSelf: "center",
    padding: spacing.xl,
    paddingBottom: Platform.OS === "ios" ? 42 : spacing.xl,
    borderTopLeftRadius: radii.xl,
    borderTopRightRadius: radii.xl,
    borderWidth: 1,
    borderColor: colors.border,
  },
  handle: { width: 42, height: 4, backgroundColor: colors.textMuted, borderRadius: 2, alignSelf: "center", marginBottom: spacing.lg },
  titleRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" },
  title: { ...type.h2, color: colors.text },
  subtitle: { ...type.small, color: colors.textSecondary, marginTop: 3 },
  close: { width: 44, height: 44, alignItems: "center", justifyContent: "center", borderRadius: 22, backgroundColor: "rgba(255,255,255,0.04)" },
  input: {
    minHeight: 150,
    marginTop: spacing.xl,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    borderRadius: radii.lg,
    backgroundColor: "rgba(5,7,16,0.72)",
    padding: spacing.md,
    color: colors.text,
    ...type.body,
    textAlignVertical: "top",
  },
  hintRow: { marginTop: spacing.sm },
  hint: { ...type.caption, color: colors.textMuted },
  error: { ...type.caption, color: colors.error, marginTop: spacing.sm },
  buttonWrap: { marginTop: spacing.xl, borderRadius: radii.md, overflow: "hidden" },
  buttonPressed: { opacity: 0.8, transform: [{ scale: 0.99 }] },
  button: { minHeight: 54, alignItems: "center", justifyContent: "center" },
  buttonText: { ...type.bodyMedium, color: colors.text },
});
