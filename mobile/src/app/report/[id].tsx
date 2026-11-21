import { Stack, useLocalSearchParams } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Alert, Image, Pressable, RefreshControl, ScrollView, StyleSheet, View } from "react-native";
import MapView, { Marker } from "react-native-maps";
import Animated, { FadeInDown, ZoomIn } from "react-native-reanimated";
import Ionicons from "@expo/vector-icons/Ionicons";
import * as ImagePicker from "expo-image-picker";
import { ShareCard, useShareReport, VoicePlayer } from "../../components/media";
import { Button, Input, MapPin, StatusPill, T, useFormatDate } from "../../components/ui";
import { api, photoUrl, type ReportDetail } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { hoursLeft, jobState } from "../../lib/fixer";
import { categoryKey, useI18n, type TKey } from "../../lib/i18n";
import { darkMapStyle } from "../../lib/mapStyle";
import { emojiFor, statusColor, useStyles, useTheme, type Palette, type Status } from "../../lib/theme";

export default function ReportScreen() {
  const { id, created } = useLocalSearchParams<{ id: string; created?: string }>();
  const { user } = useAuth();
  const { colors } = useTheme();
  const { t, tErr } = useI18n();
  const formatDate = useFormatDate();
  const s = useStyles(makeStyles);
  const [report, setReport] = useState<ReportDetail | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const { ref: cardRef, share } = useShareReport();
  const [fixPhoto, setFixPhoto] = useState<string | null>(null);
  const [fixNote, setFixNote] = useState("");
  const [fixBusy, setFixBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setReport(await api.report(Number(id)));
      setError("");
    } catch (e) {
      setError(tErr((e as Error).message));
    } finally {
      setLoading(false);
    }
  }, [id, tErr]);
  useEffect(() => void load(), [load]);

  const confirm = async () => {
    setConfirming(true);
    try {
      await api.confirm(Number(id));
      await load();
      Alert.alert(t("thanks"), t("thanksConfirm"));
    } catch (e) {
      Alert.alert("MendMap", tErr((e as Error).message));
    } finally {
      setConfirming(false);
    }
  };

  const run = async (fn: () => Promise<unknown>) => {
    setFixBusy(true);
    try {
      await fn();
      await load();
    } catch (e) {
      Alert.alert("MendMap", tErr((e as Error).message));
    } finally {
      setFixBusy(false);
    }
  };

  const askClaim = () =>
    Alert.alert(t("fixItTitle"), t("fixItBody"), [
      { text: t("cancel"), style: "cancel" },
      { text: t("fixIt"), onPress: () => run(() => api.claim(Number(id))) },
    ]);

  const takeFixPhoto = async () => {
    const perm = await ImagePicker.requestCameraPermissionsAsync();
    const opts: ImagePicker.ImagePickerOptions = { mediaTypes: ["images"], quality: 0.6, allowsEditing: true, aspect: [4, 3] };
    const res = perm.granted ? await ImagePicker.launchCameraAsync(opts) : await ImagePicker.launchImageLibraryAsync(opts);
    if (!res.canceled) setFixPhoto(res.assets[0].uri);
  };

  const sendFix = () =>
    run(async () => {
      await api.neighbourFixed(Number(id), fixPhoto!, fixNote.trim() || undefined);
      setFixPhoto(null);
      setFixNote("");
      Alert.alert(t("thanks"), t("fixSent"));
    });

  if (!report)
    return (
      <View style={s.center}>
        {error ? <T style={{ color: colors.danger }}>{error}</T> : <ActivityIndicator color={colors.accent} />}
      </View>
    );

  const mine = report.user_id === user?.id;
  const coords = { latitude: report.latitude, longitude: report.longitude };
  const catName = t(categoryKey(report.category.icon));
  // Neighbour fix: residents of the area may take safe jobs (dumping, accessibility, other).
  const job = jobState(report, user);
  const canClaim = job === "ok";
  const hours = hoursLeft(report.claim_deadline);
  const myJob = report.claimed_by === user?.id && report.status === "in_progress";
  const fixLine =
    report.fix_ai === "auto_verified" ? t("fixAi_auto_verified")
    : report.fix_status === "verified" ? t("fixVerified")
    : report.fix_status === "pending" ? t("fixPending")
    : report.claimed_by && report.status === "in_progress" && !myJob ? t("fixingBy", { name: report.claimed_by_name ?? "" })
    : null;
  // The server writes "Report submitted" on every new report; show it in the user's language.
  const comment = (c: string) => (c === "Report submitted" ? t("submitted") : c);

  return (
    <ScrollView
      contentContainerStyle={{ paddingBottom: 40 }}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={colors.accent} />}
    >
      <Stack.Screen options={{ title: `${catName} #${report.id}` }} />

      {created === "1" && (
        <Animated.View entering={ZoomIn.springify()} style={s.banner}>
          <T medium style={s.bannerTitle}>{t("onMap")}</T>
          <T style={s.bannerText}>{t("onMapBody")}</T>
        </Animated.View>
      )}

      {report.photo_url ? (
        <Image source={{ uri: photoUrl(report.photo_url)! }} style={s.photo} />
      ) : (
        <View style={[s.photo, s.center]}>
          <T style={{ fontSize: 64 }}>{emojiFor(report.category.icon)}</T>
        </View>
      )}

      <View style={s.body}>
        <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
          <T medium style={s.title}>
            {emojiFor(report.category.icon)} {catName}
          </T>
          <StatusPill status={report.status} />
        </View>
        <T style={s.desc}>{report.description || t("noDescription")}</T>
        <T style={s.muted}>
          {t("reportedOn", { d: formatDate(report.created_at) })}
          {report.confirmations > 0 ? `  ·  ${t("confirmedBy", { n: report.confirmations })}` : ""}
        </T>

        <View style={s.chips}>
          {!!report.neighbourhood && <T style={s.chip}>📍 {report.neighbourhood}</T>}
          {!!report.severity && <T style={s.chip}>{t("severityN", { s: report.severity })}</T>}
          {report.status !== "fixed" && report.priority > 0 && (
            <T style={[s.chip, { color: report.priority >= 60 ? colors.orange : colors.text }]}>{t("priorityN", { n: report.priority })}</T>
          )}
          {report.status !== "fixed" &&
            (report.priority_reasons ?? []).map((r) => (
              <T key={r} style={[s.chip, s.chipMuted]}>{t(`reason_${r}` as TKey)}</T>
            ))}
        </View>

        {report.flagged && (
          <View style={s.flagBox}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
              <Ionicons name="warning" size={18} color={colors.danger} />
              <T medium style={{ flex: 1, color: colors.danger }}>{t("flagTitle")}</T>
            </View>
            {(report.ai_flags ?? []).map((f) => (
              <T key={f} style={{ fontSize: 13 }}>
                • {f === "reused_photo" && report.reused_from ? t("flag_reused_photo_n", { id: report.reused_from })
                   : f === "fake_photo" ? t("aiFakePhoto", { kind: t(`kind_${report.ai_photo_kind ?? "edited"}` as TKey) })
                   : t(`flag_${f}` as TKey)}
              </T>
            ))}
            {!!report.ai_kind_reason && report.ai_photo_kind !== "real_photo" && (
              <T style={[s.muted, { fontStyle: "italic" }]}>“{report.ai_kind_reason}”</T>
            )}
            <T style={s.muted}>{t("flagNote")}</T>
          </View>
        )}

        {!!report.fix_ai && report.fix_ai !== "auto_verified" && report.fix_status === "pending" && (
          <View style={[s.jobInfo, report.fix_ai !== "looks_fixed" && { backgroundColor: colors.danger + "18" }]}>
            <Ionicons name="sparkles" size={18} color={report.fix_ai === "looks_fixed" ? colors.fixed : colors.danger} />
            <View style={{ flex: 1, gap: 2 }}>
              <T style={{ fontSize: 14 }}>{t(`fixAi_${report.fix_ai}` as TKey)}</T>
              {!!report.fix_ai_reason && <T style={[s.muted, { fontStyle: "italic" }]}>“{report.fix_ai_reason}”</T>}
            </View>
          </View>
        )}

        {report.ai_is_problem != null && (
          <View style={s.aiPanel}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
              <Ionicons name="sparkles" size={16} color={colors.accent} />
              <T medium style={{ flex: 1 }}>{t("aiCheckTitle")}</T>
              {report.ai_is_problem && report.ai_neighbour_safe != null && (
                <T medium style={{ fontSize: 13, color: report.ai_neighbour_safe ? colors.fixed : colors.orange }}>
                  {report.ai_neighbour_safe ? `✓ ${t("aiSafeShort")}` : `⚠ ${t("aiCrewShort")}`}
                </T>
              )}
            </View>
            {report.ai_is_problem ? (
              <T style={s.muted}>
                {t("aiLooksLike", { cat: t(categoryKey(report.ai_category ?? "other")), s: report.ai_severity ?? 3 })}
              </T>
            ) : (
              <T style={{ color: colors.danger, fontSize: 13 }}>{t("aiNotProblemFlag")}</T>
            )}
            {!!report.ai_reason && <T style={[s.muted, { fontStyle: "italic" }]}>“{report.ai_reason}”</T>}
          </View>
        )}

        {!!report.voice_url && <VoicePlayer uri={photoUrl(report.voice_url)!} />}
        {!!report.voice_text && <T style={[s.desc, s.transcript]}>“{report.voice_text}”</T>}

        <Button
          title={t("share")}
          variant="ghost"
          onPress={() => share(report)}
          icon={<Ionicons name="share-outline" size={18} color={colors.text} />}
        />

        <View style={s.map}>
          <MapView
            style={StyleSheet.absoluteFill}
            initialRegion={{ ...coords, latitudeDelta: 0.004, longitudeDelta: 0.004 }}
            customMapStyle={colors.scheme === "dark" ? darkMapStyle : []}
            userInterfaceStyle={colors.scheme}
            scrollEnabled={false}
            zoomEnabled={false}
          >
            <Marker key={colors.scheme} coordinate={coords} anchor={{ x: 0.5, y: 1 }} tracksViewChanges={false}>
              <MapPin status={report.status} icon={report.category.icon} />
            </Marker>
          </MapView>
        </View>

        {!!fixLine && (
          <View style={s.fixLine}>
            <Ionicons name="hammer" size={16} color={colors.fixed} />
            <T style={{ flex: 1, color: colors.fixed }}>{fixLine}</T>
          </View>
        )}

        {canClaim && (
          <View style={s.jobBox}>
            <T medium style={{ fontSize: 16 }}>🛠️ {t("canFixTitle")}</T>
            <T style={s.muted}>{t("earnBadge")}</T>
            <Button
              title={t("fixIt")}
              variant="orange"
              onPress={askClaim}
              loading={fixBusy}
              icon={<Ionicons name="hammer" size={18} color="#fff" />}
            />
          </View>
        )}
        {job === "unsafe" && (
          <View style={s.jobInfo}>
            <Ionicons name="shield-outline" size={18} color={colors.muted} />
            <View style={{ flex: 1, gap: 2 }}>
              <T style={{ color: colors.muted }}>{t("jobUnsafe")}</T>
              {!!report.ai_safety_reason && <T style={[s.muted, { fontStyle: "italic" }]}>“{report.ai_safety_reason}”</T>}
            </View>
          </View>
        )}
        {job === "flagged" && (
          <View style={s.jobInfo}>
            <Ionicons name="warning-outline" size={18} color={colors.muted} />
            <T style={{ flex: 1, color: colors.muted }}>{t("jobFlagged")}</T>
          </View>
        )}
        {job === "crew" && (
          <View style={s.jobInfo}>
            <Ionicons name="construct-outline" size={18} color={colors.muted} />
            <T style={{ flex: 1, color: colors.muted }}>{t("jobNeedsCrew")}</T>
          </View>
        )}

        {myJob && (
          <View style={s.fixBox}>
            <T medium style={{ fontSize: 16 }}>🛠️ {t("fixYours")}</T>
            {hours != null && (
              <T style={{ color: hours <= 6 ? colors.danger : colors.orange }}>⏱ {t("jobDeadline", { h: hours })}</T>
            )}
            <Pressable onPress={takeFixPhoto} style={s.fixPhoto}>
              {fixPhoto ? (
                <Image source={{ uri: fixPhoto }} style={StyleSheet.absoluteFill} />
              ) : (
                <>
                  <Ionicons name="camera" size={28} color={colors.orange} />
                  <T medium>{t("afterPhoto")}</T>
                </>
              )}
            </Pressable>
            <Input placeholder={t("fixComment")} value={fixNote} onChangeText={setFixNote} maxLength={500} />
            <Button title={t("sendAfter")} onPress={sendFix} loading={fixBusy} disabled={!fixPhoto} />
            <Button title={t("handBack")} variant="ghost" onPress={() => run(() => api.unclaim(Number(id)))} />
          </View>
        )}

        {!mine && report.status !== "fixed" && !myJob && user?.role === "citizen" && <Button title={t("iSeeThisToo")} onPress={confirm} loading={confirming} />}

        <T medium style={s.section}>{t("timeline")}</T>
        <View style={s.timeline}>
          {[...(report.updates ?? [])].reverse().map((u, i) => {
            const color = statusColor(colors, u.new_status as Status) ?? colors.muted;
            return (
              <Animated.View key={u.id} entering={FadeInDown.delay(i * 80)} style={s.event}>
                <View style={[s.eventDot, { borderColor: color }, i === 0 && { backgroundColor: color }]} />
                <View style={{ flex: 1, gap: 2 }}>
                  <T medium style={s.eventTitle}>{u.new_status === "fixed" ? t("mended") : t(u.new_status as TKey)}</T>
                  {!!u.comment && <T style={s.desc}>{comment(u.comment)}</T>}
                  <T style={s.muted}>{formatDate(u.created_at)}</T>
                </View>
              </Animated.View>
            );
          })}
        </View>
      </View>

      {/* Off-screen card that becomes the shared image. */}
      <View style={s.offscreen} pointerEvents="none">
        <ShareCard ref={cardRef} report={report} />
      </View>
    </ScrollView>
  );
}

const makeStyles = (c: Palette) =>
  StyleSheet.create({
    center: { flex: 1, alignItems: "center", justifyContent: "center" },
    banner: { margin: 16, marginBottom: 0, padding: 16, borderRadius: 16, backgroundColor: c.blue },
    bannerTitle: { color: "#fff", fontSize: 18 },
    bannerText: { color: "#fff", opacity: 0.9, marginTop: 4 },
    photo: { width: "100%", aspectRatio: 4 / 3, backgroundColor: c.surface, marginTop: 16 },
    body: { padding: 16, gap: 12 },
    title: { fontSize: 22, flexShrink: 1 },
    desc: { fontSize: 15, lineHeight: 21 },
    muted: { color: c.muted, fontSize: 13 },
    map: { height: 150, borderRadius: 16, overflow: "hidden", backgroundColor: c.surface },
    section: { fontSize: 17, marginTop: 8 },
    timeline: { borderLeftWidth: 2, borderLeftColor: c.line, marginLeft: 6, gap: 18, paddingVertical: 4 },
    event: { flexDirection: "row", gap: 14, marginLeft: -8 },
    eventDot: { width: 14, height: 14, borderRadius: 7, borderWidth: 3, backgroundColor: c.bg, marginTop: 3 },
    eventTitle: { fontSize: 15 },
    chips: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
    chip: { fontSize: 13, paddingHorizontal: 10, paddingVertical: 5, borderRadius: 999, backgroundColor: c.surface2, overflow: "hidden" },
    chipMuted: { color: c.muted },
    transcript: { fontStyle: "italic", color: c.muted, paddingLeft: 12, borderLeftWidth: 2, borderLeftColor: c.line },
    fixLine: { flexDirection: "row", alignItems: "center", gap: 8, padding: 10, borderRadius: 12, backgroundColor: c.fixed + "1f" },
    fixBox: { gap: 10, padding: 14, borderRadius: 16, borderWidth: 1.5, borderColor: c.orange, backgroundColor: c.surface },
    fixPhoto: {
      width: "100%", aspectRatio: 4 / 3, borderRadius: 12, overflow: "hidden", alignItems: "center", justifyContent: "center",
      gap: 6, borderWidth: 1.5, borderStyle: "dashed", borderColor: c.orange, backgroundColor: c.surface2,
    },
    jobBox: { gap: 8, padding: 14, borderRadius: 16, borderWidth: 1.5, borderColor: c.orange, backgroundColor: c.orange + "14" },
    flagBox: { gap: 4, padding: 12, borderRadius: 14, backgroundColor: c.danger + "14", borderWidth: 1, borderColor: c.danger + "55" },
    aiPanel: { gap: 4, padding: 12, borderRadius: 14, backgroundColor: c.blue + "14", borderWidth: 1, borderColor: c.blue + "33" },
    jobInfo: { flexDirection: "row", alignItems: "center", gap: 10, padding: 12, borderRadius: 14, backgroundColor: c.surface2 },
    offscreen: { position: "absolute", left: -1000, top: 0 },
  });
