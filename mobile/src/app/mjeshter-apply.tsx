import Ionicons from "@expo/vector-icons/Ionicons";
import * as DocumentPicker from "expo-document-picker";
import * as ImagePicker from "expo-image-picker";
import { router } from "expo-router";
import { useState } from "react";
import { ActivityIndicator, Alert, Image, Pressable, ScrollView, StyleSheet, View } from "react-native";
import { AreaPicker } from "../components/area";
import { Button, Input, T } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useI18n, type TKey } from "../lib/i18n";
import { DAYS, SKILL_ICON, SKILLS } from "../lib/mjeshtrit";
import { useStyles, useTheme, type Palette } from "../lib/theme";

type Proof = { uri: string; name: string; mime: string };

/** Sign up as a mjeshtër: skills, free days, area, and proof of the skill that the AI checks. */
export default function MjeshterApplyScreen() {
  const { user, updateUser } = useAuth();
  const { colors } = useTheme();
  const { t, tErr, lang } = useI18n();
  const s = useStyles(makeStyles);
  const [skills, setSkills] = useState<string[]>([]);
  const [days, setDays] = useState<string[]>(["sunday"]);
  const [area, setArea] = useState<string | null>(user?.neighbourhood ?? null);
  const [bio, setBio] = useState("");
  const [proof, setProof] = useState<Proof | null>(null);
  const [busy, setBusy] = useState(false);

  const toggle = (list: string[], set: (v: string[]) => void, k: string) =>
    set(list.includes(k) ? list.filter((x) => x !== k) : [...list, k]);

  const photo = async (camera: boolean) => {
    if (camera) {
      const perm = await ImagePicker.requestCameraPermissionsAsync();
      if (!perm.granted) return Alert.alert(t("camera"), t("cameraPerm"));
    }
    const opts: ImagePicker.ImagePickerOptions = { mediaTypes: ["images"], quality: 0.8 };
    const res = camera ? await ImagePicker.launchCameraAsync(opts) : await ImagePicker.launchImageLibraryAsync(opts);
    if (!res.canceled) {
      const a = res.assets[0];
      setProof({ uri: a.uri, name: a.fileName ?? "certificate.jpg", mime: a.mimeType ?? "image/jpeg" });
    }
  };
  const pdf = async () => {
    const res = await DocumentPicker.getDocumentAsync({ type: ["application/pdf", "image/*"], copyToCacheDirectory: true });
    if (!res.canceled) {
      const a = res.assets[0];
      setProof({ uri: a.uri, name: a.name, mime: a.mimeType ?? "application/pdf" });
    }
  };

  const ready = skills.length > 0 && !!proof && !busy;

  const submit = async () => {
    if (!proof) return;
    setBusy(true);
    try {
      const me = await api.mjeshterApply({ skills, days, neighbourhood: area, bio: bio.trim(), proof, lang });
      updateUser(await api.me());
      const [title, body] =
        me.status === "approved" ? [t("mjDoneOk"), t("mjDoneOkBody", { skills: me.verified_skills.map((k) => t(`skill_${k}` as TKey)).join(", ") })]
        : me.status === "rejected" ? [t("mjDoneBad"), me.ai_reason_user || t("mjDoneBadBody")]
        : [t("mjPending"), t("mjPendingBody")];
      Alert.alert(title, body, [{ text: "OK", onPress: () => router.back() }]);
    } catch (e) {
      Alert.alert("MendMap", tErr((e as Error).message));
    } finally {
      setBusy(false);
    }
  };

  return (
    <ScrollView contentContainerStyle={s.page} keyboardShouldPersistTaps="handled">
      <T style={s.muted}>{t("mjApplyIntro")}</T>

      <T medium style={s.step}>1. {t("mjSkills")}</T>
      <View style={s.chips}>
        {SKILLS.map((k) => {
          const on = skills.includes(k);
          return (
            <Pressable key={k} onPress={() => toggle(skills, setSkills, k)} style={[s.chip, on && s.chipOn]}>
              <T medium style={{ color: on ? colors.onBlue : colors.text }}>{SKILL_ICON[k]} {t(`skill_${k}` as TKey)}</T>
            </Pressable>
          );
        })}
      </View>
      <T style={s.hint}>{t("mjSafetyNote")}</T>

      <T medium style={s.step}>2. {t("mjDays")}</T>
      <View style={s.chips}>
        {DAYS.map((k) => {
          const on = days.includes(k);
          return (
            <Pressable key={k} onPress={() => toggle(days, setDays, k)} style={[s.chip, on && s.chipOn]}>
              <T medium style={{ color: on ? colors.onBlue : colors.text }}>{t(`day_${k}` as TKey)}</T>
            </Pressable>
          );
        })}
      </View>

      <T medium style={s.step}>3. {t("myArea")}</T>
      <AreaPicker value={area} onChange={setArea} />

      <T medium style={s.step}>4. {t("mjBio")}</T>
      <Input value={bio} onChangeText={setBio} placeholder={t("mjBioHint")} maxLength={500} multiline style={{ minHeight: 70 }} />

      <T medium style={s.step}>5. {t("mjProof")}</T>
      <T style={s.hint}>{t("mjProofHint")}</T>
      {proof ? (
        <View style={s.proof}>
          {proof.mime.startsWith("image/") ? (
            <Image source={{ uri: proof.uri }} style={s.proofImg} />
          ) : (
            <View style={[s.proofImg, { alignItems: "center", justifyContent: "center" }]}>
              <Ionicons name="document-text" size={34} color={colors.accent} />
            </View>
          )}
          <T style={{ flex: 1 }} numberOfLines={2}>{proof.name}</T>
          <Pressable onPress={() => setProof(null)} hitSlop={10}>
            <Ionicons name="close-circle" size={24} color={colors.muted} />
          </Pressable>
        </View>
      ) : (
        <View style={{ flexDirection: "row", gap: 8 }}>
          <Button title={t("mjProofPhoto")} variant="ghost" onPress={() => photo(true)} style={{ flex: 1 }}
            icon={<Ionicons name="camera" size={18} color={colors.accent} />} />
          <Button title={t("mjProofFile")} variant="ghost" onPress={() => Alert.alert(t("mjProof"), undefined, [
            { text: t("mjFromPhotos"), onPress: () => photo(false) },
            { text: "PDF", onPress: pdf },
            { text: t("cancel"), style: "cancel" },
          ])} style={{ flex: 1 }} icon={<Ionicons name="document-attach" size={18} color={colors.accent} />} />
        </View>
      )}
      <View style={s.privacy}>
        <Ionicons name="lock-closed" size={14} color={colors.muted} />
        <T style={[s.hint, { flex: 1 }]}>{t("mjPrivacy")}</T>
      </View>

      {busy && (
        <View style={s.checking}>
          <ActivityIndicator color={colors.accent} />
          <T style={{ flex: 1 }}>{t("mjChecking")}</T>
        </View>
      )}
      <Button title={t("mjSend")} variant="orange" onPress={submit} loading={busy} disabled={!ready} style={{ marginTop: 6 }} />
      {!ready && !busy && <T style={[s.hint, { textAlign: "center" }]}>{t("mjNeed")}</T>}
    </ScrollView>
  );
}

const makeStyles = (c: Palette) =>
  StyleSheet.create({
    page: { padding: 16, gap: 10, paddingBottom: 48 },
    step: { fontSize: 16, marginTop: 10 },
    chips: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
    chip: { paddingHorizontal: 14, paddingVertical: 9, borderRadius: 999, backgroundColor: c.surface2, borderWidth: 1, borderColor: c.line },
    chipOn: { backgroundColor: c.blue, borderColor: c.blue },
    hint: { color: c.muted, fontSize: 13 },
    muted: { color: c.muted },
    proof: { flexDirection: "row", alignItems: "center", gap: 12, padding: 10, borderRadius: 14, backgroundColor: c.surface, borderWidth: 1, borderColor: c.line },
    proofImg: { width: 64, height: 64, borderRadius: 10, backgroundColor: c.surface2 },
    privacy: { flexDirection: "row", alignItems: "center", gap: 6 },
    checking: { flexDirection: "row", alignItems: "center", gap: 10, padding: 12, borderRadius: 12, backgroundColor: c.blue + "1f" },
  });
