import Ionicons from "@expo/vector-icons/Ionicons";
import NetInfo from "@react-native-community/netinfo";
import * as ImagePicker from "expo-image-picker";
import * as Location from "expo-location";
import { router, useFocusEffect } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, Alert, Image, Keyboard, KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, StyleSheet, View } from "react-native";
import MapView from "react-native-maps";
import { VoiceRecorder } from "../../components/media";
import { Button, Input, MapPin, StatusPill, T, useTimeAgo } from "../../components/ui";
import { api, ApiError, photoUrl, type Category, type PhotoCheck, type Place, type Report } from "../../lib/api";
import { addDraft, subscribeDrafts, syncDrafts, type Draft } from "../../lib/drafts";
import { categoryKey, useI18n, type TKey } from "../../lib/i18n";
import { darkMapStyle } from "../../lib/mapStyle";
import { emojiFor, useStyles, useTheme, type Palette } from "../../lib/theme";

type Coords = { latitude: number; longitude: number };
const DUPLICATE_RADIUS_M = 40;
const PRISHTINA: Coords = { latitude: 42.6629, longitude: 21.1655 };

export default function NewReport() {
  const mapRef = useRef<MapView>(null);
  const { colors } = useTheme();
  const { t, tErr, updateCountryFrom, lang } = useI18n();
  const timeAgo = useTimeAgo();
  const s = useStyles(makeStyles);
  const [categories, setCategories] = useState<Category[]>([]);
  const [categoryId, setCategoryId] = useState<number | null>(null);
  const [photo, setPhoto] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [coords, setCoords] = useState<Coords | null>(null);
  const [mapTouch, setMapTouch] = useState(false);
  // Street box: typed by the user (with suggestions) or filled in from the pin's position.
  const [street, setStreet] = useState("");
  const [places, setPlaces] = useState<Place[] | null>(null);
  const [searching, setSearching] = useState(false);
  const typing = useRef(false); // the user is writing: don't overwrite the box from the pin
  const picked = useRef(false); // the map is moving to a picked street: keep its name
  const [locError, setLocError] = useState("");
  const [busy, setBusy] = useState(false);
  const [dupes, setDupes] = useState<Report[] | null>(null);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [voice, setVoice] = useState<string | null>(null);
  const [check, setCheck] = useState<PhotoCheck | null>(null);
  const [checking, setChecking] = useState(false);
  const [severity, setSeverity] = useState<number | null>(null);
  const [aiNote, setAiNote] = useState<string | null>(null); // the description the AI wrote, while untouched
  const aiNoteRef = useRef<string | null>(null);

  useEffect(() => subscribeDrafts(setDrafts), []);
  useEffect(() => {
    api.categories().then(setCategories).catch(() =>
      // Offline on first launch: still allow drafting with the known categories.
      setCategories([
        { id: 1, name: "Pothole", icon: "pothole" },
        { id: 2, name: "Streetlight", icon: "streetlight" },
        { id: 3, name: "Illegal dumping", icon: "dumping" },
        { id: 4, name: "Other", icon: "other" },
        { id: 5, name: "Accessibility", icon: "accessibility" },
      ]),
    );
  }, []);

  const locate = useCallback(async () => {
    setLocError("");
    const { status } = await Location.requestForegroundPermissionsAsync();
    if (status !== "granted") {
      setLocError(t("locPermOff"));
      setCoords((c) => c ?? PRISHTINA);
      return;
    }
    try {
      const pos = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High });
      const c = { latitude: pos.coords.latitude, longitude: pos.coords.longitude };
      setCoords(c);
      mapRef.current?.animateToRegion({ ...c, latitudeDelta: 0.003, longitudeDelta: 0.003 }, 400);
      updateCountryFrom(c);
    } catch {
      setLocError(t("gpsFail"));
      setCoords((c) => c ?? PRISHTINA);
    }
  }, [t, updateCountryFrom]);

  // The street under the pin (after GPS or moving the map), shown in the street box.
  const streetAt = useCallback(async (c: Coords) => {
    if (typing.current) return;
    try {
      const [place] = await Location.reverseGeocodeAsync(c);
      const name = place?.street ?? place?.name ?? null;
      if (name && !typing.current) setStreet(place?.streetNumber && place.street ? `${place.street} ${place.streetNumber}` : name);
    } catch {
      // No geocoder (offline, no permission): the box just stays as it is.
    }
  }, []);

  // Suggestions while typing (after a short pause, so not every letter is a search).
  const searchTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const typeStreet = (v: string) => {
    typing.current = true;
    setStreet(v);
    clearTimeout(searchTimer.current);
    const q = v.trim();
    if (q.length < 2) {
      setPlaces(null);
      setSearching(false);
      return;
    }
    setSearching(true);
    searchTimer.current = setTimeout(async () => {
      try {
        const found = await api.searchStreets(q);
        if (typing.current) setPlaces(found);
      } catch {
        setPlaces([]);
      } finally {
        setSearching(false);
      }
    }, 350);
  };
  useEffect(() => () => clearTimeout(searchTimer.current), []);

  const pickPlace = (p: Place) => {
    typing.current = false;
    picked.current = true;
    clearTimeout(searchTimer.current);
    Keyboard.dismiss();
    setPlaces(null);
    setStreet(p.detail && p.kind === "place" ? `${p.name}, ${p.detail}` : p.name);
    const c = { latitude: p.latitude, longitude: p.longitude };
    setCoords(c);
    mapRef.current?.animateToRegion({ ...c, latitudeDelta: 0.002, longitudeDelta: 0.002 }, 450);
  };

  // GPS fills in the location every time the tab opens on a fresh report.
  useFocusEffect(useCallback(() => { if (!photo && !categoryId) void locate(); }, [locate, photo, categoryId]));

  const pickPhoto = async (fromCamera: boolean) => {
    if (fromCamera) {
      const perm = await ImagePicker.requestCameraPermissionsAsync();
      if (!perm.granted) return Alert.alert(t("camera"), t("cameraPerm"));
    }
    const opts: ImagePicker.ImagePickerOptions = { mediaTypes: ["images"], quality: 0.6, allowsEditing: true, aspect: [4, 3] };
    const res = fromCamera ? await ImagePicker.launchCameraAsync(opts) : await ImagePicker.launchImageLibraryAsync(opts);
    if (!res.canceled) void applyPhoto(res.assets[0].uri);
  };

  // AI check: suggests a category and severity, and flags photos that don't show a street problem.
  const applyPhoto = async (uri: string) => {
    setPhoto(uri);
    setCheck(null);
    setChecking(true);
    try {
      const r = await api.checkPhoto(uri, lang);
      setCheck(r);
      if (r.available && r.is_street_problem) {
        if (r.severity) setSeverity(r.severity);
        // The AI writes the description from the photo, unless the citizen already wrote one.
        const desc = r.description?.trim();
        if (desc) {
          setNote((cur) => {
            if (cur.trim() && cur !== aiNoteRef.current) return cur;
            aiNoteRef.current = desc;
            setAiNote(desc);
            return desc;
          });
        }
        const match = categories.find((c) => c.icon === r.category);
        if (match) setCategoryId((cur) => cur ?? match.id);
      }
    } catch {
      setCheck(null); // offline or no AI: just carry on
    } finally {
      setChecking(false);
    }
  };
  const fakeKind = check?.available && check.photo_kind && check.photo_kind !== "real_photo" ? check.photo_kind : null;
  const rejected = !!check?.available && (check.is_street_problem === false || !!fakeKind);

  const reset = () => {
    setPhoto(null);
    setStreet("");
    setPlaces(null);
    setNote("");
    setCategoryId(null);
    setDupes(null);
    setVoice(null);
    setCheck(null);
    setSeverity(null);
    setAiNote(null);
    aiNoteRef.current = null;
  };

  const payload = () => ({
    categoryId: categoryId!,
    latitude: coords!.latitude,
    longitude: coords!.longitude,
    description: note.trim() || undefined,
    address: street.trim() || undefined,
    photoUri: photo,
    voiceUri: voice,
    severity,
  });

  const saveDraft = async () => {
    const cat = categories.find((c) => c.id === categoryId);
    await addDraft(payload(), cat ? t(categoryKey(cat.icon)) : t("report"));
    reset();
    Alert.alert(t("savedOfflineTitle"), t("savedOfflineBody"));
  };

  /** Only call it "offline" when the phone really has no connection. */
  const phoneOffline = async () => {
    const st = await NetInfo.fetch();
    return !st.isConnected || st.isInternetReachable === false;
  };

  const send = async (): Promise<void> => {
    setBusy(true);
    try {
      const report = await api.createReport(payload());
      reset();
      router.push(`/report/${report.id}?created=1`);
    } catch (e) {
      const network = e instanceof ApiError && (e.status === 0 || e.status === 502 || e.status === 503 || e.status === 504);
      if (!network) {
        Alert.alert(t("couldntSend"), tErr((e as Error).message));
      } else if (await phoneOffline()) {
        await saveDraft();
      } else {
        // Online but the server didn't answer: say so, and let the user choose.
        Alert.alert(t("couldntSend"), t("serverDown"), [
          { text: t("saveForLater"), onPress: () => void saveDraft() },
          { text: t("tryAgain"), style: "default", onPress: () => void send() },
        ]);
      }
    } finally {
      setBusy(false);
    }
  };

  const submit = async () => {
    if (!photo || !categoryId || !coords) return;
    setBusy(true);
    try {
      // Duplicate check: open reports of the same category close by.
      const nearby = await api.reports({
        near: { lat: coords.latitude, lng: coords.longitude },
        radius: DUPLICATE_RADIUS_M,
        category: categoryId,
        status: "reported,in_progress",
      });
      if (nearby.length) {
        setDupes(nearby);
        setBusy(false);
        return;
      }
    } catch (e) {
      setBusy(false);
      if (e instanceof ApiError && e.status === 0 && (await phoneOffline())) return saveDraft();
      // Duplicate check failed for another reason: still try to send the report.
    }
    await send();
  };

  const confirmExisting = async (r: Report) => {
    try {
      await api.confirm(r.id);
      reset();
      Alert.alert(t("thanks"), t("thanksConfirm"));
      router.push(`/report/${r.id}`);
    } catch (e) {
      Alert.alert("MendMap", tErr((e as Error).message));
    }
  };

  // A photo is required: the city uses it to judge the problem before sending a crew.
  const ready = !!photo && !!categoryId && !!coords && !rejected; // never wait on the AI to send

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined} keyboardVerticalOffset={90}>
      <ScrollView contentContainerStyle={s.scroll} keyboardShouldPersistTaps="handled" scrollEnabled={!mapTouch}>
        {drafts.length > 0 && (
          <Pressable style={s.drafts} onPress={() => syncDrafts()}>
            <Ionicons name="cloud-offline" size={18} color={colors.amber} />
            <T medium style={s.draftsText}>{t("draftsWaiting", { n: drafts.length })}</T>
          </Pressable>
        )}

        {/* 1. Snap it (required) */}
        <View style={s.stepRow}>
          <T medium style={s.step}>{t("step1")}</T>
          <T style={[s.required, !!photo && { color: colors.fixed }]}>{photo ? "✓" : "*"}</T>
        </View>
        {photo ? (
          <View>
            <Image source={{ uri: photo }} style={s.photo} />
            <Pressable style={s.retake} onPress={() => { setPhoto(null); setCheck(null); }} accessibilityLabel="Remove photo">
              <Ionicons name="close" color="#fff" size={18} />
            </Pressable>
            {checking && (
              <View style={s.aiBox}>
                <ActivityIndicator size="small" color={colors.accent} />
                <T style={s.hint}>{t("aiChecking")}</T>
              </View>
            )}
            {!checking && check?.available && check.is_street_problem && (
              <View style={s.aiBox}>
                <Ionicons name="sparkles" size={16} color={colors.accent} />
                <View style={{ flex: 1, gap: 2 }}>
                  <T style={{ fontSize: 13 }}>
                    {t("aiLooksLike", { cat: t(categoryKey(check.category ?? "other")), s: check.severity ?? 3 })}
                  </T>
                  {(check.blur_boxes?.length ?? 0) > 0 && (
                    <T style={{ fontSize: 12, color: colors.muted }}>🔒 {t("aiWillBlur", { n: check.blur_boxes!.length })}</T>
                  )}
                  {check.neighbour_safe != null && (
                    <T style={{ fontSize: 12, color: check.neighbour_safe ? colors.fixed : colors.muted }}>
                      {check.neighbour_safe ? `✓ ${t("aiSafeLong")}` : t("aiCrewLong")}
                    </T>
                  )}
                </View>
              </View>
            )}
            {!checking && rejected && (
              <View style={[s.aiBox, { backgroundColor: colors.danger + "22" }]}>
                <Ionicons name="alert-circle" size={18} color={colors.danger} />
                <T style={{ flex: 1, fontSize: 13, color: colors.danger }}>
                  {fakeKind ? t("aiFakePhoto", { kind: t(`kind_${fakeKind}` as TKey) }) : t("aiNotProblem")}
                </T>
                <Pressable onPress={() => pickPhoto(true)} hitSlop={8}>
                  <T medium style={{ color: colors.accent }}>{t("aiRetake")}</T>
                </Pressable>
              </View>
            )}
          </View>
        ) : (
          <>
            <View style={s.photoRow}>
              <Pressable style={[s.photoBtn, { borderColor: colors.orange }]} onPress={() => pickPhoto(true)}>
                <Ionicons name="camera" size={30} color={colors.orange} />
                <T medium>{t("takePhoto")}</T>
              </Pressable>
              <Pressable style={s.photoBtn} onPress={() => pickPhoto(false)}>
                <Ionicons name="images" size={28} color={colors.muted} />
                <T medium>{t("fromGallery")}</T>
              </Pressable>
            </View>
            <T style={s.hint}>{t("photoRequired")}</T>
          </>
        )}

        {/* 2. Category */}
        <T medium style={s.step}>{t("step2")}</T>
        <View style={s.cats}>
          {categories.map((c) => {
            const on = categoryId === c.id;
            return (
              <Pressable key={c.id} onPress={() => setCategoryId(c.id)} style={[s.cat, on && s.catActive]}>
                <T style={{ fontSize: 26 }}>{emojiFor(c.icon)}</T>
                <T medium style={[s.catText, on && { color: colors.text }]}>{t(categoryKey(c.icon))}</T>
              </Pressable>
            );
          })}
        </View>

        {/* Severity */}
        <View style={s.sevRow}>
          {[1, 2, 3, 4, 5].map((n) => (
            <Pressable
              key={n}
              onPress={() => setSeverity(severity === n ? null : n)}
              style={[s.sev, severity !== null && n <= severity && { backgroundColor: colors.orange + "33", borderColor: colors.orange }]}
              accessibilityLabel={t("severityN", { s: n })}
            >
              <T medium style={{ color: severity !== null && n <= severity ? colors.orange : colors.muted }}>{n}</T>
            </Pressable>
          ))}
          <T style={[s.hint, { flex: 1, textAlign: "right" }]}>{severity ? t("severityN", { s: severity }) : t("severityN", { s: "–" })}</T>
        </View>

        {/* 3. Location */}
        <View style={s.stepRow}>
          <T medium style={s.step}>{t("step3")}</T>
          <Pressable onPress={locate} hitSlop={10} style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
            <Ionicons name="locate" size={16} color={colors.accent} />
            <T medium style={{ color: colors.accent }}>{t("useMyLocation")}</T>
          </Pressable>
        </View>
        <View style={{ gap: 6, zIndex: 2 }}>
          <View style={s.streetBox}>
            <Ionicons name="search" size={18} color={colors.muted} />
            <Input
              style={s.streetInput}
              value={street}
              placeholder={t("streetPlaceholder")}
              onChangeText={typeStreet}
              onBlur={() => {
                typing.current = false;
              }}
              returnKeyType="search"
              onSubmitEditing={() => places?.[0] && pickPlace(places[0])}
              autoCorrect={false}
            />
            {searching ? (
              <ActivityIndicator size="small" color={colors.accent} />
            ) : !!street && (
              <Pressable
                onPress={() => typeStreet("")}
                hitSlop={10}
              >
                <Ionicons name="close-circle" size={18} color={colors.muted} />
              </Pressable>
            )}
          </View>
          {places && (
            <View style={s.suggestions}>
              {places.length === 0 && !searching && <T style={[s.hint, { padding: 12 }]}>{t("streetNone")}</T>}
              {places.map((p, i) => (
                <Pressable
                  key={`${p.name}-${p.latitude}-${i}`}
                  onPress={() => pickPlace(p)}
                  style={({ pressed }) => [s.suggestion, i > 0 && s.suggestionLine, pressed && { opacity: 0.6 }]}
                >
                  <Ionicons name={p.kind === "street" ? "trail-sign-outline" : "location-outline"} size={18} color={colors.accent} />
                  <View style={{ flex: 1 }}>
                    <T medium numberOfLines={1}>{p.name}</T>
                    {!!p.detail && <T style={s.hint} numberOfLines={1}>{p.detail}</T>}
                  </View>
                </Pressable>
              ))}
            </View>
          )}
        </View>
        <View
          style={s.mapBox}
          // Moving the map must not scroll the page.
          onTouchStart={() => setMapTouch(true)}
          onTouchEnd={() => setMapTouch(false)}
          onTouchCancel={() => setMapTouch(false)}
        >
          {coords ? (
            <>
              {/* The pin stays in the middle; the user moves the map under it (or taps a spot). */}
              <MapView
                ref={mapRef}
                style={StyleSheet.absoluteFill}
                initialRegion={{ ...coords, latitudeDelta: 0.003, longitudeDelta: 0.003 }}
                customMapStyle={colors.scheme === "dark" ? darkMapStyle : []}
                userInterfaceStyle={colors.scheme}
                showsUserLocation
                onRegionChangeComplete={(r) => {
                  const c = { latitude: r.latitude, longitude: r.longitude };
                  setCoords(c);
                  if (picked.current) picked.current = false;
                  else void streetAt(c);
                }}
                onPress={(e) => mapRef.current?.animateCamera({ center: e.nativeEvent.coordinate }, { duration: 250 })}
              />
              <View pointerEvents="none" style={s.centerPin}>
                <MapPin status="reported" icon={categories.find((c) => c.id === categoryId)?.icon ?? "other"} selected />
              </View>
            </>
          ) : (
            <ActivityIndicator color={colors.accent} style={{ flex: 1 }} />
          )}
        </View>
        <T style={s.hint}>{locError || t("dragHint")}</T>

        {/* 4. Note */}
        <T medium style={s.step}>{t("step4")}</T>
        <Input
          style={s.note}
          placeholder={t("notePlaceholder")}
          value={note}
          onChangeText={setNote}
          multiline
          maxLength={2000}
        />
        {!!aiNote && note === aiNote && (
          <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
            <Ionicons name="sparkles" size={14} color={colors.accent} />
            <T style={[s.hint, { flex: 1 }]}>{t("aiWroteNote")}</T>
            <Pressable onPress={() => { setNote(""); setAiNote(null); }} hitSlop={8}>
              <T medium style={{ color: colors.accent, fontSize: 13 }}>{t("clear")}</T>
            </Pressable>
          </View>
        )}
        <T style={s.hint}>{t("voiceNote")}</T>
        <VoiceRecorder uri={voice} onChange={setVoice} />

        <Button title={t("send")} variant="orange" onPress={submit} loading={busy} disabled={!ready} style={{ marginTop: 8 }} />
        {!ready && <T style={[s.hint, { textAlign: "center" }]}>{t("needPhotoAndCategory")}</T>}
      </ScrollView>

      {/* Duplicate check */}
      <Modal visible={!!dupes} transparent animationType="slide" onRequestClose={() => setDupes(null)}>
        <View style={s.sheetBackdrop}>
          <View style={s.sheet}>
            <T medium style={s.sheetTitle}>{t("dupTitle")}</T>
            <T style={s.hint}>{t("dupBody")}</T>
            <ScrollView style={{ maxHeight: 320 }} contentContainerStyle={{ gap: 10, paddingVertical: 12 }}>
              {dupes?.map((r) => (
                <View key={r.id} style={s.dupe}>
                  {r.photo_url ? (
                    <Image source={{ uri: photoUrl(r.photo_url)! }} style={s.dupePhoto} />
                  ) : (
                    <View style={[s.dupePhoto, { alignItems: "center", justifyContent: "center" }]}>
                      <T style={{ fontSize: 26 }}>{emojiFor(r.category.icon)}</T>
                    </View>
                  )}
                  <View style={{ flex: 1, gap: 4 }}>
                    <T medium>
                      {emojiFor(r.category.icon)} {t(categoryKey(r.category.icon))} · {t("mAway", { n: Math.round(r.distance_m ?? 0) })}
                    </T>
                    <StatusPill status={r.status} />
                    <T style={s.hint} numberOfLines={2}>
                      {r.description || t("noDescription")} · {timeAgo(r.created_at)}
                    </T>
                  </View>
                  <Button title={t("iSeeThisToo")} onPress={() => confirmExisting(r)} style={{ height: 42, paddingHorizontal: 12 }} />
                </View>
              ))}
            </ScrollView>
            <Button title={t("differentProblem")} variant="ghost" onPress={() => { setDupes(null); void send(); }} />
          </View>
        </View>
      </Modal>
    </KeyboardAvoidingView>
  );
}

const makeStyles = (c: Palette) =>
  StyleSheet.create({
    scroll: { padding: 16, paddingBottom: 40, gap: 10 },
    step: { fontSize: 16, marginTop: 10 },
    required: { color: c.orange, fontSize: 16 },
    stepRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-end" },
    hint: { color: c.muted, fontSize: 13 },
    drafts: { flexDirection: "row", gap: 8, alignItems: "center", padding: 12, borderRadius: 12, backgroundColor: c.amber + "22" },
    draftsText: { color: c.amber, flex: 1 },
    photoRow: { flexDirection: "row", gap: 12 },
    photoBtn: {
      flex: 1, height: 130, borderRadius: 16, borderWidth: 1.5, borderStyle: "dashed", borderColor: c.line,
      alignItems: "center", justifyContent: "center", gap: 8, backgroundColor: c.surface,
    },
    photo: { width: "100%", aspectRatio: 4 / 3, borderRadius: 16, backgroundColor: c.surface },
    retake: { position: "absolute", top: 10, right: 10, backgroundColor: "#000a", borderRadius: 999, padding: 6 },
    cats: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
    cat: {
      width: "48%", flexGrow: 1, flexDirection: "row", alignItems: "center", gap: 10, padding: 14, borderRadius: 14,
      backgroundColor: c.surface, borderWidth: 1.5, borderColor: c.line,
    },
    catActive: { borderColor: c.blue, backgroundColor: c.blue + "26" },
    catText: { color: c.muted, flexShrink: 1 },
    streetBox: {
      flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: 12, borderRadius: 14,
      backgroundColor: c.surface, borderWidth: 1, borderColor: c.line,
    },
    streetInput: { flex: 1, borderWidth: 0, backgroundColor: "transparent", paddingHorizontal: 0 },
    suggestions: { borderRadius: 14, backgroundColor: c.surface, borderWidth: 1, borderColor: c.line, overflow: "hidden" },
    suggestion: { flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: 12, paddingVertical: 10 },
    suggestionLine: { borderTopWidth: 1, borderTopColor: c.line },
    mapBox: { height: 220, borderRadius: 16, overflow: "hidden", backgroundColor: c.surface },
    // MapPin's tip is at its bottom centre: lift it so the tip sits exactly on the map's centre.
    centerPin: { position: "absolute", left: 0, right: 0, top: 0, bottom: "50%", alignItems: "center", justifyContent: "flex-end" },
    note: { minHeight: 90, height: undefined, paddingVertical: 14, fontSize: 15, textAlignVertical: "top" },
    aiBox: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 8, padding: 10, borderRadius: 12, backgroundColor: c.blue + "1f" },
    sevRow: { flexDirection: "row", alignItems: "center", gap: 8 },
    sev: { width: 40, height: 40, borderRadius: 12, alignItems: "center", justifyContent: "center", borderWidth: 1.5, borderColor: c.line, backgroundColor: c.surface },
    sheetBackdrop: { flex: 1, justifyContent: "flex-end", backgroundColor: "#000a" },
    sheet: { backgroundColor: c.surface, padding: 20, paddingBottom: 36, borderTopLeftRadius: 24, borderTopRightRadius: 24, gap: 6 },
    sheetTitle: { fontSize: 20 },
    dupePhoto: { width: 64, height: 64, borderRadius: 10, backgroundColor: c.surface },
    dupe: { flexDirection: "row", alignItems: "center", gap: 10, padding: 12, borderRadius: 14, backgroundColor: c.surface2 },
  });
