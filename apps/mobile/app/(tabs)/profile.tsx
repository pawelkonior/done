import { useEffect, useState } from "react";
import {
  Bell,
  ChevronRight,
  CircleCheck,
  CreditCard,
  Gauge,
  Globe2,
  MapPin,
  ShieldCheck,
  UserRound,
} from "lucide-react-native";
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { AppScreen } from "@/components/AppScreen";
import { GlassCard } from "@/components/GlassCard";
import { PageHeader } from "@/components/PageHeader";
import { ChoiceRow, PreferenceModal } from "@/components/PreferenceModal";
import { useUpdateUserProfile, useUserProfile } from "@/api/hooks";
import type { DeliveryAddress, UserProfileUpdate } from "@/types/domain";
import { colors, radii, spacing, type } from "@/theme/tokens";

type ProfileDialog = "account" | "region" | "autonomy" | "address" | "payment" | "constraints" | "contact" | null;

const localeOptions = [
  { value: "pl-PL", label: "Polski (Polska)" },
  { value: "en-PL", label: "English (Poland)" },
  { value: "en-US", label: "English (United States)" },
];

const autonomyOptions = [
  { value: "guarded", label: "Guarded", description: "Ask before most decisions" },
  { value: "balanced", label: "Balanced", description: "Act autonomously within your constraints" },
  { value: "autonomous", label: "Autonomous", description: "Interrupt only for required approvals" },
];

const contactOptions = [
  { value: "only_when_needed", label: "Only when needed", description: "Important decisions and blocked missions" },
  { value: "important_updates", label: "Important updates", description: "Decisions, recoveries and meaningful mission changes" },
  { value: "all_updates", label: "All updates", description: "Every mission state change" },
];

const friendlyValue = (value: string) => value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
const errorMessage = (error: unknown) => error instanceof Error ? error.message : "Couldn’t save profile changes.";

const emptyAddress: DeliveryAddress = { label: "Home", line1: "", city: "", postal_code: "", country: "PL" };

export default function ProfileScreen() {
  const profileQuery = useUserProfile();
  const update = useUpdateUserProfile();
  const profile = profileQuery.data;
  const [dialog, setDialog] = useState<ProfileDialog>(null);
  const [nameDraft, setNameDraft] = useState("");
  const [emailDraft, setEmailDraft] = useState("");
  const [localeDraft, setLocaleDraft] = useState("");
  const [currencyDraft, setCurrencyDraft] = useState("");
  const [timezoneDraft, setTimezoneDraft] = useState("");
  const [autonomyDraft, setAutonomyDraft] = useState("");
  const [addressDraft, setAddressDraft] = useState<DeliveryAddress>(emptyAddress);
  const [brandDraft, setBrandDraft] = useState("");
  const [last4Draft, setLast4Draft] = useState("");
  const [expiryMonthDraft, setExpiryMonthDraft] = useState("");
  const [expiryYearDraft, setExpiryYearDraft] = useState("");
  const [constraintsDraft, setConstraintsDraft] = useState("");
  const [contactDraft, setContactDraft] = useState("");

  const resetDrafts = () => {
    if (!profile) return;
    setNameDraft(profile.name);
    setEmailDraft(profile.email);
    setLocaleDraft(profile.locale);
    setCurrencyDraft(profile.currency);
    setTimezoneDraft(profile.timezone);
    setAutonomyDraft(profile.autonomy_level);
    setAddressDraft(profile.delivery_address);
    setBrandDraft(profile.payment_method.brand);
    setLast4Draft(profile.payment_method.last4);
    setExpiryMonthDraft(String(profile.payment_method.expiry_month));
    setExpiryYearDraft(String(profile.payment_method.expiry_year));
    setConstraintsDraft(profile.default_constraints.join("\n"));
    setContactDraft(profile.contact_preference);
  };

  useEffect(resetDrafts, [profile]);

  const openDialog = (next: Exclude<ProfileDialog, null>) => {
    if (!profile) return;
    update.reset();
    resetDrafts();
    setDialog(next);
  };

  const save = async (payload: UserProfileUpdate) => {
    try {
      await update.mutateAsync(payload);
      setDialog(null);
    } catch {
      // The modal stays open with an actionable API error.
    }
  };

  const mutationError = update.error ? errorMessage(update.error) : null;
  const expiryMonth = Number(expiryMonthDraft);
  const expiryYear = Number(expiryYearDraft);
  const constraints = constraintsDraft.split(/[\n,]+/).map((value) => value.trim()).filter(Boolean);
  const validEmail = /^\S+@\S+\.\S+$/.test(emailDraft.trim());
  const validPayment = /^\d{4}$/.test(last4Draft) && expiryMonth >= 1 && expiryMonth <= 12 && expiryYear >= new Date().getFullYear();

  return (
    <AppScreen testID="profile-screen">
      <PageHeader title="Profile" subtitle="Your defaults make every mission faster and safer." />

      {!profile ? (
        <QueryState
          loading={profileQuery.isLoading}
          error={profileQuery.error ? errorMessage(profileQuery.error) : null}
          onRetry={() => void profileQuery.refetch()}
        />
      ) : (
        <>
          {mutationError && !dialog ? <InlineError message={mutationError} /> : null}
          <View style={styles.profileHero}>
            <LinearGradient colors={[colors.primary, "#45219A"]} style={styles.avatar}>
              <Text style={styles.initials}>{initials(profile.name)}</Text>
            </LinearGradient>
            <Text style={styles.name}>{profile.name}</Text>
            <Text style={styles.email}>{profile.email}</Text>
            <View style={styles.verified}>
              <CircleCheck size={15} color={colors.success} />
              <Text style={styles.verifiedText}>{profile.payment_method.is_demo ? "Demo profile synced" : "Profile synced"}</Text>
            </View>
          </View>

          <GlassCard style={styles.stats}>
            <Stat value={String(profile.stats.missions)} label="Missions" />
            <View style={styles.divider} />
            <Stat value={String(profile.stats.recoveries)} label="Recoveries" />
            <View style={styles.divider} />
            <Stat value={`${formatMoney(profile.stats.saved)} ${profile.currency}`} label="Saved" />
          </GlassCard>

          <Text style={styles.sectionTitle}>Account & region</Text>
          <GlassCard style={styles.rows}>
            <ProfileRow icon={UserRound} label="Personal details" value={profile.email} onPress={() => openDialog("account")} testID="profile-account" />
            <ProfileRow icon={Globe2} label="Region" value={`${profile.locale} · ${profile.currency}`} onPress={() => openDialog("region")} testID="profile-region" />
            <ProfileRow icon={Gauge} label="Autonomy" value={friendlyValue(profile.autonomy_level)} onPress={() => openDialog("autonomy")} testID="profile-autonomy" />
          </GlassCard>

          <Text style={styles.sectionTitle}>Mission defaults</Text>
          <GlassCard style={styles.rows}>
            <ProfileRow icon={MapPin} label="Delivery address" value={addressSummary(profile.delivery_address)} onPress={() => openDialog("address")} testID="profile-address" />
            <ProfileRow icon={CreditCard} label="Payment method" value={`${profile.payment_method.brand} •••• ${profile.payment_method.last4}`} onPress={() => openDialog("payment")} testID="profile-payment" />
            <ProfileRow icon={ShieldCheck} label="Hard constraints" value={profile.default_constraints.length ? `${profile.default_constraints.length} saved` : "None"} onPress={() => openDialog("constraints")} testID="profile-constraints" />
            <ProfileRow icon={Bell} label="Contact preference" value={friendlyValue(profile.contact_preference)} onPress={() => openDialog("contact")} testID="profile-contact" />
          </GlassCard>
        </>
      )}

      <PreferenceModal
        visible={dialog === "account"}
        title="Personal details"
        description="Keep your profile name and contact email current."
        onClose={() => setDialog(null)}
        onSave={() => void save({ name: nameDraft.trim(), email: emailDraft.trim() })}
        saving={update.isPending}
        saveDisabled={!nameDraft.trim() || !validEmail}
        error={dialog === "account" && mutationError ? mutationError : null}
        testID="account-modal"
      >
        <FormField label="Name" value={nameDraft} onChangeText={setNameDraft} placeholder="Your name" testID="profile-name-input" />
        <FormField label="Email" value={emailDraft} onChangeText={setEmailDraft} placeholder="you@example.com" keyboardType="email-address" autoCapitalize="none" testID="profile-email-input" />
      </PreferenceModal>

      <PreferenceModal
        visible={dialog === "region"}
        title="Region"
        description="These defaults control currency, dates and mission deadlines."
        onClose={() => setDialog(null)}
        onSave={() => void save({ locale: localeDraft, currency: currencyDraft.trim().toUpperCase(), timezone: timezoneDraft.trim() })}
        saving={update.isPending}
        saveDisabled={!localeDraft || currencyDraft.trim().length !== 3 || !timezoneDraft.trim()}
        error={dialog === "region" && mutationError ? mutationError : null}
        testID="region-modal"
      >
        <Text style={styles.inputLabel}>Locale</Text>
        <View accessibilityRole="radiogroup" style={styles.choiceList}>
          {localeOptions.map((option) => <ChoiceRow key={option.value} label={option.label} selected={localeDraft === option.value} onPress={() => setLocaleDraft(option.value)} />)}
        </View>
        <FormField label="Currency" value={currencyDraft} onChangeText={setCurrencyDraft} placeholder="PLN" autoCapitalize="characters" maxLength={3} />
        <FormField label="Timezone" value={timezoneDraft} onChangeText={setTimezoneDraft} placeholder="Europe/Warsaw" autoCapitalize="none" />
      </PreferenceModal>

      <PreferenceModal
        visible={dialog === "autonomy"}
        title="Autonomy level"
        description="Choose how often Done should interrupt you. Hard constraints are never relaxed automatically."
        onClose={() => setDialog(null)}
        onSave={() => void save({ autonomy_level: autonomyDraft })}
        saving={update.isPending}
        error={dialog === "autonomy" && mutationError ? mutationError : null}
        testID="autonomy-modal"
      >
        <View accessibilityRole="radiogroup" style={styles.choiceList}>
          {autonomyOptions.map((option) => <ChoiceRow key={option.value} label={option.label} description={option.description} selected={autonomyDraft === option.value} onPress={() => setAutonomyDraft(option.value)} />)}
        </View>
      </PreferenceModal>

      <PreferenceModal
        visible={dialog === "address"}
        title="Delivery address"
        description="Used as the default destination for commerce missions."
        onClose={() => setDialog(null)}
        onSave={() => void save({ delivery_address: addressDraft })}
        saving={update.isPending}
        saveDisabled={!addressDraft.label.trim() || !addressDraft.line1.trim() || !addressDraft.city.trim() || !addressDraft.postal_code.trim() || !addressDraft.country.trim()}
        error={dialog === "address" && mutationError ? mutationError : null}
        testID="address-modal"
      >
        <FormField label="Label" value={addressDraft.label} onChangeText={(label) => setAddressDraft((current) => ({ ...current, label }))} placeholder="Home" />
        <FormField label="Street and number" value={addressDraft.line1} onChangeText={(line1) => setAddressDraft((current) => ({ ...current, line1 }))} placeholder="Prosta 20" testID="profile-address-line1" />
        <FormField label="City" value={addressDraft.city} onChangeText={(city) => setAddressDraft((current) => ({ ...current, city }))} placeholder="Warsaw" />
        <View style={styles.inlineFields}>
          <View style={styles.inlineField}><FormField label="Postal code" value={addressDraft.postal_code} onChangeText={(postal_code) => setAddressDraft((current) => ({ ...current, postal_code }))} placeholder="00-001" /></View>
          <View style={styles.inlineField}><FormField label="Country" value={addressDraft.country} onChangeText={(country) => setAddressDraft((current) => ({ ...current, country: country.toUpperCase() }))} placeholder="PL" maxLength={2} autoCapitalize="characters" /></View>
        </View>
      </PreferenceModal>

      <PreferenceModal
        visible={dialog === "payment"}
        title="Payment method"
        description="Demo card details are tokenized; the full card number is never stored here."
        onClose={() => setDialog(null)}
        onSave={() => void save({ payment_method: { brand: brandDraft.trim(), last4: last4Draft, expiry_month: expiryMonth, expiry_year: expiryYear } })}
        saving={update.isPending}
        saveDisabled={!brandDraft.trim() || !validPayment}
        error={dialog === "payment" && mutationError ? mutationError : null}
        testID="payment-modal"
      >
        <FormField label="Card brand" value={brandDraft} onChangeText={setBrandDraft} placeholder="Visa" />
        <FormField label="Last four digits" value={last4Draft} onChangeText={(value) => setLast4Draft(value.replace(/\D/g, ""))} placeholder="4242" keyboardType="number-pad" maxLength={4} testID="profile-payment-last4" />
        <View style={styles.inlineFields}>
          <View style={styles.inlineField}><FormField label="Expiry month" value={expiryMonthDraft} onChangeText={(value) => setExpiryMonthDraft(value.replace(/\D/g, ""))} placeholder="12" keyboardType="number-pad" maxLength={2} /></View>
          <View style={styles.inlineField}><FormField label="Expiry year" value={expiryYearDraft} onChangeText={(value) => setExpiryYearDraft(value.replace(/\D/g, ""))} placeholder="2030" keyboardType="number-pad" maxLength={4} /></View>
        </View>
      </PreferenceModal>

      <PreferenceModal
        visible={dialog === "constraints"}
        title="Hard constraints"
        description="Enter one constraint per line. Done must preserve all of them."
        onClose={() => setDialog(null)}
        onSave={() => void save({ default_constraints: constraints })}
        saving={update.isPending}
        saveDisabled={!constraints.length}
        error={dialog === "constraints" && mutationError ? mutationError : null}
        testID="constraints-modal"
      >
        <Text style={styles.inputLabel}>Default constraints</Text>
        <TextInput
          multiline
          value={constraintsDraft}
          onChangeText={setConstraintsDraft}
          placeholder={"No nuts\nDelivery only to my saved address"}
          placeholderTextColor={colors.textMuted}
          style={[styles.input, styles.multiline]}
          textAlignVertical="top"
          testID="profile-constraints-input"
        />
      </PreferenceModal>

      <PreferenceModal
        visible={dialog === "contact"}
        title="Contact preference"
        description="Choose when Done should notify you during a mission."
        onClose={() => setDialog(null)}
        onSave={() => void save({ contact_preference: contactDraft })}
        saving={update.isPending}
        error={dialog === "contact" && mutationError ? mutationError : null}
        testID="contact-modal"
      >
        <View accessibilityRole="radiogroup" style={styles.choiceList}>
          {contactOptions.map((option) => <ChoiceRow key={option.value} label={option.label} description={option.description} selected={contactDraft === option.value} onPress={() => setContactDraft(option.value)} />)}
        </View>
      </PreferenceModal>
    </AppScreen>
  );
}

function initials(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return parts.slice(0, 2).map((part) => part[0]?.toUpperCase() ?? "").join("") || "D";
}

function formatMoney(value: number) {
  return new Intl.NumberFormat("en", { maximumFractionDigits: 0 }).format(value);
}

function addressSummary(address: DeliveryAddress) {
  return [address.label, address.city].filter(Boolean).join(" · ") || "Add address";
}

function Stat({ value, label }: { value: string; label: string }) {
  return <View style={styles.stat}><Text numberOfLines={1} style={styles.statValue}>{value}</Text><Text style={styles.statLabel}>{label}</Text></View>;
}

function ProfileRow({ icon: Icon, label, value, onPress, testID }: { icon: typeof MapPin; label: string; value: string; onPress: () => void; testID?: string }) {
  return (
    <Pressable accessibilityRole="button" onPress={onPress} style={({ pressed }) => [styles.row, pressed && styles.pressed]} testID={testID}>
      <View style={styles.rowIcon}><Icon size={20} color={colors.primaryBright} /></View>
      <View style={styles.rowText}><Text style={styles.rowLabel}>{label}</Text><Text numberOfLines={1} style={styles.rowValue}>{value}</Text></View>
      <ChevronRight size={18} color={colors.textMuted} />
    </Pressable>
  );
}

function FormField({ label, ...props }: { label: string } & React.ComponentProps<typeof TextInput>) {
  return (
    <View style={styles.field}>
      <Text style={styles.inputLabel}>{label}</Text>
      <TextInput placeholderTextColor={colors.textMuted} style={styles.input} {...props} />
    </View>
  );
}

function QueryState({ loading, error, onRetry }: { loading: boolean; error: string | null; onRetry: () => void }) {
  return (
    <GlassCard style={styles.queryState}>
      {loading ? <ActivityIndicator color={colors.primaryBright} /> : null}
      <Text style={styles.queryStateText}>{loading ? "Loading profile…" : error ?? "Profile isn’t available."}</Text>
      {!loading ? <Pressable onPress={onRetry} style={styles.retryButton}><Text style={styles.retryText}>Try again</Text></Pressable> : null}
    </GlassCard>
  );
}

function InlineError({ message }: { message: string }) {
  return <View style={styles.errorBanner}><Text accessibilityRole="alert" style={styles.errorText}>{message}</Text></View>;
}

const styles = StyleSheet.create({
  profileHero: { alignItems: "center", paddingVertical: spacing.md },
  avatar: { width: 92, height: 92, borderRadius: 46, alignItems: "center", justifyContent: "center", borderWidth: 2, borderColor: colors.primaryBright },
  initials: { ...type.h1, color: colors.text },
  name: { ...type.h2, color: colors.text, marginTop: spacing.md },
  email: { ...type.small, color: colors.textSecondary, marginTop: 2 },
  verified: { flexDirection: "row", alignItems: "center", gap: 5, marginTop: spacing.sm, paddingVertical: 5, paddingHorizontal: 9, borderRadius: radii.round, backgroundColor: "rgba(72,214,106,0.08)" },
  verifiedText: { ...type.caption, color: colors.success },
  stats: { flexDirection: "row", alignItems: "center", padding: spacing.md, marginTop: spacing.lg },
  stat: { flex: 1, alignItems: "center", minWidth: 0 },
  statValue: { ...type.h3, color: colors.text, maxWidth: "100%" },
  statLabel: { ...type.caption, color: colors.textSecondary, marginTop: 3 },
  divider: { width: 1, height: 42, backgroundColor: colors.hairline },
  sectionTitle: { ...type.eyebrow, color: colors.textSecondary, marginTop: spacing.xxl, marginBottom: spacing.xs, paddingLeft: spacing.xs },
  rows: { overflow: "hidden" },
  row: { minHeight: 70, paddingHorizontal: spacing.md, flexDirection: "row", alignItems: "center", gap: spacing.sm, borderBottomWidth: 1, borderBottomColor: colors.hairline },
  rowIcon: { width: 40, height: 40, borderRadius: 13, backgroundColor: "rgba(155,92,255,0.08)", alignItems: "center", justifyContent: "center" },
  rowText: { flex: 1, minWidth: 0 },
  rowLabel: { ...type.smallMedium, color: colors.text },
  rowValue: { ...type.caption, color: colors.textSecondary, textTransform: "capitalize" },
  pressed: { opacity: 0.68 },
  choiceList: { gap: spacing.xs },
  field: { gap: spacing.xs },
  inputLabel: { ...type.caption, color: colors.textSecondary },
  input: { minHeight: 52, borderWidth: 1, borderColor: colors.borderStrong, borderRadius: radii.md, backgroundColor: "rgba(5,7,16,0.72)", paddingHorizontal: spacing.md, color: colors.text, ...type.body },
  multiline: { minHeight: 150, paddingTop: spacing.md },
  inlineFields: { flexDirection: "row", gap: spacing.sm },
  inlineField: { flex: 1 },
  queryState: { minHeight: 150, padding: spacing.lg, alignItems: "center", justifyContent: "center", gap: spacing.sm },
  queryStateText: { ...type.small, color: colors.textSecondary, textAlign: "center" },
  retryButton: { minHeight: 42, paddingHorizontal: spacing.md, borderRadius: radii.md, borderWidth: 1, borderColor: colors.border, alignItems: "center", justifyContent: "center" },
  retryText: { ...type.smallMedium, color: colors.primaryBright },
  errorBanner: { borderWidth: 1, borderColor: "rgba(255,93,115,0.25)", backgroundColor: "rgba(255,93,115,0.07)", borderRadius: radii.md, padding: spacing.sm, marginBottom: spacing.md },
  errorText: { ...type.caption, color: colors.error },
});
