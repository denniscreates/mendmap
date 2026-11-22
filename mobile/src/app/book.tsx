import Ionicons from "@expo/vector-icons/Ionicons";
import * as ImagePicker from "expo-image-picker";
import { router, useLocalSearchParams } from "expo-router";
import { useState } from "react";
import { Alert, Image, KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, View } from "react-native";
import { Button, Input, T } from "../components/ui";
import { api } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { useStyles, useTheme, type Palette } from "../lib/theme";

/** Ask a mjeshtër for a price: a photo of the job (so they see how big it is) and a few words. */
export default function Book() {
  const { mj, name, skill, report } = useLocalSearchParams<{ mj: string; name?: string; skill?: string; report?: string }>();
  const { colors } = useTheme();
  const { t, tErr } = useI18n();
  const s = useStyles(makeStyles);
  const [photo, setPhoto] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [address, setAddress] = useState("");
  const [busy, setBusy] = useState(false);

  const pick = async (fromCamera: boolean) => {
    if (fromCamera) {
      const perm = await ImagePicker.requestCameraPermissionsAsync();
      if (!perm.granted) return Alert.alert(t("camera"), t("cameraPerm"));
    }
    const opts: ImagePicker.ImagePickerOptions = { mediaTypes: ["images"], quality: 0.6, allowsEditing: true, aspect: [4, 3] };
    const res = fromCamera ? await ImagePicker.launchCameraAsync(opts) : await ImagePicker.launchImageLibraryAsync(opts);
    if (!res.canceled) setPhoto(res.assets[0].uri);
  };

  const ready = !!photo && text.trim().length >= 5;
  const send = async () => {
    if (!ready || !photo) return;
    setBusy(true);
    try {
      const b = await api.createBooking({
        mjeshterId: Number(mj), description: text.trim(), photoUri: photo,
        address: address.trim() || undefined, reportId: report ? Number(report) : undefined, skill: skill || undefined,
      });
      router.replace(`/booking/${b.id}`);
    } catch (e) {
      Alert.alert("MendMap", tErr((e as Error).message));
    } finally {
      setBusy(false);
    }
  };

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
      <ScrollView contentContainerStyle={s.page} keyboardShouldPersistTaps="handled">
        <View style={s.hero}>
          <View style={s.avatar}><T medium style={{ color: "#fff", fontSize: 20 }}>{(name ?? "?")[0]}</T></View>
          <T style={{ flex: 1 }}>{t("bkIntro", { name: name ?? "" })}</T>
        </View>

        {photo ? (
          <Pressable onPress={() => void pick(true)}>
            <Image source={{ uri: photo }} style={s.photo} />
            <View style={s.retake}><Ionicons name="camera-reverse" size={18} color="#fff" /></View>
          </Pressable>
        ) : (
          <View style={{ flexDirection: "row", gap: 10 }}>
            <Pressable style={[s.pickBox, { borderColor: colors.orange }]} onPress={() => void pick(true)}>
              <Ionicons name="camera" size={30} color={colors.orange} />
              <T medium>{t("bkPhoto")}</T>
            </Pressable>
            <Pressable style={s.pickBox} onPress={() => void pick(false)}>
              <Ionicons name="images" size={30} color={colors.accent} />
              <T medium>{t("bkLibrary")}</T>
            </Pressable>
          </View>
        )}

        <T medium style={s.label}>{t("bkWhat")}</T>
        <Input value={text} onChangeText={setText} placeholder={t("bkWhatPh")} multiline maxLength={1000}
          style={{ height: 100, paddingTop: 12, textAlignVertical: "top" }} />
        <T medium style={s.label}>{t("bkWhere")}</T>
        <Input value={address} onChangeText={setAddress} placeholder={t("streetPlaceholder")} maxLength={200} />

        <Button title={t("bkSend")} variant="orange" onPress={send} loading={busy} disabled={!ready}
          icon={<Ionicons name="paper-plane" size={18} color="#fff" />} style={{ marginTop: 12 }} />
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const makeStyles = (c: Palette) =>
  StyleSheet.create({
    page: { padding: 16, gap: 10, paddingBottom: 60 },
    hero: { flexDirection: "row", alignItems: "center", gap: 12, padding: 14, borderRadius: 18, backgroundColor: c.surface2 },
    avatar: { width: 44, height: 44, borderRadius: 22, alignItems: "center", justifyContent: "center", backgroundColor: c.blue },
    pickBox: { flex: 1, height: 130, borderRadius: 18, borderWidth: 2, borderStyle: "dashed", borderColor: c.line, alignItems: "center", justifyContent: "center", gap: 8, backgroundColor: c.surface },
    photo: { width: "100%", aspectRatio: 4 / 3, borderRadius: 18, backgroundColor: c.surface2 },
    retake: { position: "absolute", right: 10, bottom: 10, padding: 8, borderRadius: 20, backgroundColor: "#0008" },
    label: { marginTop: 8, fontSize: 15 },
  });
