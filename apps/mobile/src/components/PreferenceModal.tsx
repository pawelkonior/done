import type { PropsWithChildren } from "react";
import { ActivityIndicator, KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { X } from "lucide-react-native";
import { LinearGradient } from "expo-linear-gradient";
import { colors, radii, spacing, type } from "@/theme/tokens";

interface PreferenceModalProps extends PropsWithChildren {
  visible: boolean;
  title: string;
  description?: string;
  onClose: () => void;
  onSave?: () => void;
  saveLabel?: string;
  saving?: boolean;
  saveDisabled?: boolean;
  error?: string | null;
  testID?: string;
}

export function PreferenceModal({
  visible,
  title,
  description,
  onClose,
  onSave,
  saveLabel = "Save changes",
  saving = false,
  saveDisabled = false,
  error,
  testID,
  children,
}: PreferenceModalProps) {
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={styles.backdrop}>
        <Pressable style={StyleSheet.absoluteFill} onPress={onClose} accessibilityLabel="Close dialog" />
        <View style={styles.sheet} testID={testID}>
          <View style={styles.handle} />
          <View style={styles.header}>
            <View style={styles.heading}>
              <Text style={styles.title}>{title}</Text>
              {description ? <Text style={styles.description}>{description}</Text> : null}
            </View>
            <Pressable onPress={onClose} accessibilityRole="button" accessibilityLabel="Close" style={styles.close}>
              <X size={21} color={colors.textSecondary} />
            </Pressable>
          </View>
          <ScrollView
            style={styles.scroller}
            contentContainerStyle={styles.content}
            keyboardShouldPersistTaps="handled"
            showsVerticalScrollIndicator={false}
          >
            {children}
          </ScrollView>
          {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
          {onSave ? (
            <View style={styles.actions}>
              <Pressable onPress={onClose} disabled={saving} style={({ pressed }) => [styles.cancel, pressed && styles.pressed]}>
                <Text style={styles.cancelText}>Cancel</Text>
              </Pressable>
              <Pressable
                onPress={onSave}
                disabled={saving || saveDisabled}
                accessibilityRole="button"
                accessibilityState={{ disabled: saving || saveDisabled }}
                style={({ pressed }) => [styles.saveWrap, (saving || saveDisabled) && styles.disabled, pressed && styles.pressed]}
                testID={testID ? `${testID}-save` : undefined}
              >
                <LinearGradient colors={[colors.primary, "#7442EA"]} style={styles.save}>
                  {saving ? <ActivityIndicator color={colors.text} size="small" /> : null}
                  <Text style={styles.saveText}>{saving ? "Saving…" : saveLabel}</Text>
                </LinearGradient>
              </Pressable>
            </View>
          ) : null}
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

export function ChoiceRow({
  label,
  description,
  selected,
  onPress,
  multiple = false,
  testID,
}: {
  label: string;
  description?: string;
  selected: boolean;
  onPress: () => void;
  multiple?: boolean;
  testID?: string;
}) {
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole={multiple ? "checkbox" : "radio"}
      accessibilityState={{ checked: selected }}
      style={({ pressed }) => [styles.choice, selected && styles.choiceSelected, pressed && styles.pressed]}
      testID={testID}
    >
      <View style={[styles.choiceIndicator, multiple && styles.checkbox, selected && styles.choiceIndicatorSelected]}>
        {selected ? <View style={[styles.choiceDot, multiple && styles.checkboxDot]} /> : null}
      </View>
      <View style={styles.choiceText}>
        <Text style={styles.choiceLabel}>{label}</Text>
        {description ? <Text style={styles.choiceDescription}>{description}</Text> : null}
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, justifyContent: "flex-end", backgroundColor: colors.overlay },
  sheet: {
    width: "100%",
    maxWidth: 520,
    maxHeight: "88%",
    alignSelf: "center",
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.sm,
    paddingBottom: Platform.OS === "ios" ? 34 : spacing.lg,
    borderTopLeftRadius: radii.xl,
    borderTopRightRadius: radii.xl,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  handle: { width: 42, height: 4, borderRadius: 2, backgroundColor: colors.textMuted, opacity: 0.55, alignSelf: "center", marginBottom: spacing.md },
  header: { flexDirection: "row", alignItems: "flex-start", gap: spacing.md },
  heading: { flex: 1 },
  title: { ...type.h2, color: colors.text },
  description: { ...type.small, color: colors.textSecondary, marginTop: 3 },
  close: { width: 42, height: 42, borderRadius: 21, backgroundColor: "rgba(255,255,255,0.04)", alignItems: "center", justifyContent: "center" },
  scroller: { marginTop: spacing.lg },
  content: { gap: spacing.xs, paddingBottom: spacing.xs },
  error: { ...type.caption, color: colors.error, marginTop: spacing.sm },
  actions: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.md },
  cancel: { minHeight: 50, paddingHorizontal: spacing.lg, alignItems: "center", justifyContent: "center", borderRadius: radii.md, borderWidth: 1, borderColor: colors.hairline },
  cancelText: { ...type.smallMedium, color: colors.textSecondary },
  saveWrap: { flex: 1, overflow: "hidden", borderRadius: radii.md },
  save: { minHeight: 50, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.xs },
  saveText: { ...type.bodyMedium, color: colors.text },
  disabled: { opacity: 0.42 },
  pressed: { opacity: 0.72 },
  choice: { minHeight: 62, flexDirection: "row", alignItems: "center", gap: spacing.sm, padding: spacing.sm, borderWidth: 1, borderColor: colors.hairline, borderRadius: radii.md, backgroundColor: "rgba(255,255,255,0.018)" },
  choiceSelected: { borderColor: colors.borderStrong, backgroundColor: "rgba(155,92,255,0.09)" },
  choiceIndicator: { width: 22, height: 22, borderRadius: 11, borderWidth: 2, borderColor: colors.textMuted, alignItems: "center", justifyContent: "center" },
  choiceIndicatorSelected: { borderColor: colors.primary },
  choiceDot: { width: 10, height: 10, borderRadius: 5, backgroundColor: colors.primary },
  checkbox: { borderRadius: 6 },
  checkboxDot: { width: 12, height: 12, borderRadius: 3 },
  choiceText: { flex: 1 },
  choiceLabel: { ...type.smallMedium, color: colors.text },
  choiceDescription: { ...type.caption, color: colors.textSecondary, marginTop: 2 },
});
