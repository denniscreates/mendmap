import Ionicons from "@expo/vector-icons/Ionicons";
import * as ImagePicker from "expo-image-picker";
import { router, useLocalSearchParams } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, Alert, Image, KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, View } from "react-native";
import { Button, Input, T } from "../../components/ui";
import { api, MAX_PHOTOS, photoUrl, type Category, type ReportDetail } from "../../lib/api";
import { categoryKey, useI18n } from "../../lib/i18n";
import { emojiFor, useStyles, useTheme, type Palette } from "../../lib/theme";

/** A photo in the editor: one already on the server (url) or a new one from this phone (uri). */
type Shot = { url?: string; uri?: string };
const key = (p: Shot) => p.url ?? p.uri ?? "";

/**
 * The reporter edits their post: photos (add, remove, pick the cover), category, description, street and severity.
 * Only while nobody is working on it yet. New photos are checked by the AI again on the server.
 */
export default function EditReport() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { colors } = useTheme();
  const { t, tErr } = useI18n();
  const s = useStyles(makeStyles);
  const [report, setReport] = useState<ReportDetail | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [shots, setShots] = useState<Shot[]>([]);
  const [categoryId, setCategoryId] = useState<number | null>(null);
  const [desc, setDesc] = useState("");
  const [street, setStreet] = useState("");
  const [severity, setSeverity] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([api.report(Number(id)), api.categories()])
      .then(([r, cats]) => {
        setReport(r);
        setCategories(cats);
        setShots(r.photos.map((url) => ({ url })));
        setCategoryId(r.category.id);
        setDesc(r.description ?? "");
        setStreet(r.address ?? "");
        setSeverity(r.severity);
      })
      .catch((e) => setError(tErr((e as Error).message)));
  }, [id, tErr]);

  const add = async (fromCamera: boolean) => {
    const room = MAX_PHOTOS - shots.length;
    if (room <= 0) return;
    if (fromCamera) {
      const perm = await ImagePicker.requestCameraPermissionsAsync();
      if (!perm.granted) return Alert.alert(t("camera"), t("cameraPerm"));
    }
    const res = fromCamera
      ? await ImagePicker.launchCameraAsync({ mediaTypes: ["images"], quality: 0.6, allowsEditing: true, aspect: [4, 3] })
      : await ImagePicker.launchImageLibraryAsync({ mediaTypes: ["images"], quality: 0.6, allowsMultipleSelection: true, selectionLimit: room, orderedSelection: true });
    if (!res.canceled) setShots((cur) => [...cur, ...res.assets.map((a) => ({ uri: a.uri }))].slice(0, MAX_PHOTOS));
  };

  const save = async () => {
    if (!report || !shots.length) return;
    setBusy(true);
    try {
      await api.editReport(report.id, {
        categoryId: categoryId ?? undefined,
        description: desc.trim(),
        address: street.trim(),
        severity,
        keep: shots.filter((p) => p.url).map((p) => p.url!),
        add: shots.filter((p) => p.uri).map((p) => p.uri!),
      });
      router.back();
    } catch (e) {
      Alert.alert("MendMap", tErr((e as Error).message));
    } finally {
      setBusy(false);
    }
  };

  if (!report)
    return (
      <View style={s.center}>
        {error ? <T style={{ color: colors.danger }}>{error}</T> : <ActivityIndicator color={colors.accent} />}
      </View>
    );

  const hasNew = shots.some((p) => p.uri);
  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined} keyboardVerticalOffset={90}>
      <ScrollView contentContainerStyle={s.page} keyboardShouldPersistTaps="handled">
        <T medium style={s.label}>{t("editPhotos", { n: shots.length, max: MAX_PHOTOS })}</T>
        <View style={s.grid}>
          {shots.map((p, i) => (
            <View key={key(p)}>
              <Pressable onPress={() => setShots((cur) => [p, ...cur.filter((x) => x !== p)])} accessibilityLabel={t("makeCover")}>
                <Image source={{ uri: p.url ? photoUrl(p.url)! : p.uri! }} style={[s.shot, i === 0 && { borderColor: colors.accent }]} />
              </Pressable>
              {i === 0 && <T style={s.cover}>{t("cover")}</T>}
              <Pressable style={s.x} hitSlop={6} onPress={() => setShots((cur) => cur.filter((x) => x !== p))} accessibilityLabel={t("removePhoto")}>
                <Ionicons name="close" size={14} color="#fff" />
              </Pressable>
            </View>
          ))}
          {shots.length < MAX_PHOTOS && (
            <>
              <Pressable style={s.addShot} onPress={() => add(true)} accessibilityLabel={t("takePhoto")}>
                <Ionicons name="camera" size={24} color={colors.orange} />
              </Pressable>
              <Pressable style={s.addShot} onPress={() => add(false)} accessibilityLabel={t("fromGallery")}>
                <Ionicons name="images" size={22} color={colors.muted} />
              </Pressable>
            </>
          )}
        </View>
        <T style={s.muted}>{shots.length ? t("makeCoverHint") : t("photoRequired")}</T>
        {hasNew && <T style={s.muted}>✨ {t("editAiAgain")}</T>}

        <T medium style={s.label}>{t("step2")}</T>
        <View style={s.cats}>
          {categories.map((c) => (
            <Pressable key={c.id} onPress={() => setCategoryId(c.id)} style={[s.cat, categoryId === c.id && { borderColor: colors.accent, backgroundColor: colors.accent + "22" }]}>
              <T>{emojiFor(c.icon)} {t(categoryKey(c.icon))}</T>
            </Pressable>
          ))}
        </View>

        <T medium style={s.label}>{t("editDescription")}</T>
        <Input value={desc} onChangeText={setDesc} multiline maxLength={2000} style={{ minHeight: 100 }} placeholder={t("noDescription")} />
        <T medium style={s.label}>{t("editStreet")}</T>
        <Input value={street} onChangeText={setStreet} maxLength={200} />

        <T medium style={s.label}>{t("editSeverity")}</T>
        <View style={s.sevRow}>
          {[1, 2, 3, 4, 5].map((n) => (
            <Pressable key={n} onPress={() => setSeverity(severity === n ? null : n)} accessibilityLabel={t("severityN", { s: n })}
              style={[s.sev, severity !== null && n <= severity && { backgroundColor: colors.orange + "33", borderColor: colors.orange }]}>
              <T medium style={{ color: severity !== null && n <= severity ? colors.orange : colors.muted }}>{n}</T>
            </Pressable>
          ))}
        </View>
        <T style={s.muted}>{severity ? t("severityN", { s: severity }) : t("editSeverityAi")}</T>

        <Button title={t("editSave")} onPress={save} loading={busy} disabled={!shots.length} icon={<Ionicons name="checkmark" size={18} color="#fff" />} />
        <Button title={t("cancel")} variant="ghost" onPress={() => router.back()} />
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const makeStyles = (c: Palette) =>
  StyleSheet.create({
    center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 30 },
    page: { padding: 16, gap: 10, paddingBottom: 60 },
    label: { fontSize: 16, marginTop: 8 },
    muted: { color: c.muted, fontSize: 13 },
    grid: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
    shot: { width: 100, height: 100, borderRadius: 14, borderWidth: 2, borderColor: "transparent", backgroundColor: c.surface },
    cover: { position: "absolute", left: 6, bottom: 6, fontSize: 11, color: "#fff", backgroundColor: "#000a", paddingHorizontal: 6, paddingVertical: 2, borderRadius: 8, overflow: "hidden" },
    x: { position: "absolute", top: 5, right: 5, backgroundColor: "#000a", borderRadius: 999, padding: 3 },
    addShot: { width: 100, height: 100, borderRadius: 14, borderWidth: 1, borderStyle: "dashed", borderColor: c.line, alignItems: "center", justifyContent: "center" },
    cats: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
    cat: { paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999, borderWidth: 1, borderColor: c.line, backgroundColor: c.surface },
    sevRow: { flexDirection: "row", gap: 8 },
    sev: { width: 44, height: 44, borderRadius: 12, borderWidth: 1, borderColor: c.line, alignItems: "center", justifyContent: "center" },
  });
