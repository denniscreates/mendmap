import Ionicons from "@expo/vector-icons/Ionicons";
import * as ImagePicker from "expo-image-picker";
import * as Location from "expo-location";
import { router, useFocusEffect } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, FlatList, Image, KeyboardAvoidingView, Linking, Modal, Platform, Pressable, RefreshControl, StyleSheet, View } from "react-native";
import MapView, { Marker, Polyline } from "react-native-maps";
import { Button, Input, MapPin, T } from "../../components/ui";
import { photoUrl, type Job } from "../../lib/api";
import { finishJob, loadJobs, startCrewSync, subscribeQueue, syncQueue, type Done } from "../../lib/crew";
import { categoryKey, useI18n } from "../../lib/i18n";
import { darkMapStyle } from "../../lib/mapStyle";
import { emojiFor, useStyles, useTheme, type Palette } from "../../lib/theme";

const PRISHTINA = { latitude: 42.6629, longitude: 21.1655 };

/** Crew mode: today's In progress jobs in driving order, closed with an "after" photo. Works offline. */
export default function Jobs() {
  const mapRef = useRef<MapView>(null);
  const { colors } = useTheme();
  const { t, tErr } = useI18n();
  const s = useStyles(makeStyles);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [offline, setOffline] = useState(false);
  const [loading, setLoading] = useState(false);
  const [queue, setQueue] = useState<Done[]>([]);
  const [here, setHere] = useState<{ latitude: number; longitude: number } | null>(null);
  const [active, setActive] = useState<Job | null>(null);
  const [after, setAfter] = useState<string | null>(null);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => subscribeQueue(setQueue), []);
  useEffect(() => startCrewSync(() => void load()), []); // eslint-disable-line react-hooks/exhaustive-deps

  const load = useCallback(async () => {
    setLoading(true);
    try {
      let near = here;
      if (!near) {
        const perm = await Location.getForegroundPermissionsAsync();
        if (perm.granted) {
          const pos = await Location.getLastKnownPositionAsync();
          if (pos) near = { latitude: pos.coords.latitude, longitude: pos.coords.longitude };
          setHere(near);
        }
      }
      const res = await loadJobs(near ? { lat: near.latitude, lng: near.longitude } : undefined);
      setJobs(res.jobs);
      setOffline(res.offline);
      if (res.jobs.length) {
        mapRef.current?.fitToCoordinates(
          res.jobs.map((j) => ({ latitude: j.latitude, longitude: j.longitude })),
          { edgePadding: { top: 40, right: 40, bottom: 40, left: 40 }, animated: true },
        );
      }
    } catch (e) {
      Alert.alert("MendMap", tErr((e as Error).message));
    } finally {
      setLoading(false);
    }
  }, [here, tErr]);
  useFocusEffect(useCallback(() => void load(), [load]));

  const queuedIds = new Set(queue.map((q) => q.id));
  const visible = jobs.filter((j) => !queuedIds.has(j.id));

  const takeAfter = async () => {
    const perm = await ImagePicker.requestCameraPermissionsAsync();
    const opts: ImagePicker.ImagePickerOptions = { mediaTypes: ["images"], quality: 0.6, allowsEditing: true, aspect: [4, 3] };
    const res = perm.granted ? await ImagePicker.launchCameraAsync(opts) : await ImagePicker.launchImageLibraryAsync(opts);
    if (!res.canceled) setAfter(res.assets[0].uri);
  };

  const close = () => {
    setActive(null);
    setAfter(null);
    setComment("");
  };

  const done = async () => {
    if (!active) return;
    if (!after) return Alert.alert(t("markFixed"), t("afterPhotoRequired"));
    setBusy(true);
    try {
      const r = await finishJob(active.id, after, comment.trim() || undefined);
      setJobs((js) => js.filter((j) => j.id !== active.id));
      close();
      if (r === "queued") Alert.alert(t("markFixed"), t("queuedOffline"));
    } catch (e) {
      Alert.alert("MendMap", tErr((e as Error).message));
    } finally {
      setBusy(false);
    }
  };

  const directions = (j: Job) => {
    const url = Platform.OS === "ios"
      ? `http://maps.apple.com/?daddr=${j.latitude},${j.longitude}`
      : `https://www.google.com/maps/dir/?api=1&destination=${j.latitude},${j.longitude}`;
    void Linking.openURL(url);
  };

  const route = [...(here ? [here] : []), ...visible.map((j) => ({ latitude: j.latitude, longitude: j.longitude }))];

  return (
    <View style={{ flex: 1 }}>
      <View style={s.map}>
        <MapView
          ref={mapRef}
          style={StyleSheet.absoluteFill}
          initialRegion={{ ...(here ?? PRISHTINA), latitudeDelta: 0.05, longitudeDelta: 0.05 }}
          customMapStyle={colors.scheme === "dark" ? darkMapStyle : []}
          userInterfaceStyle={colors.scheme}
          showsUserLocation
        >
          {route.length > 1 && <Polyline coordinates={route} strokeColor={colors.accent} strokeWidth={3} lineDashPattern={[8, 6]} />}
          {visible.map((j) => (
            <Marker
              key={`${j.id}-${colors.scheme}`}
              coordinate={{ latitude: j.latitude, longitude: j.longitude }}
              anchor={{ x: 0.5, y: 1 }}
              tracksViewChanges={false}
              onPress={() => setActive(j)}
            >
              <MapPin status="in_progress" icon={j.category.icon} />
            </Marker>
          ))}
        </MapView>
      </View>

      <FlatList
        data={visible}
        keyExtractor={(j) => String(j.id)}
        contentContainerStyle={{ padding: 16, gap: 10, flexGrow: 1 }}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={() => { void syncQueue(); void load(); }} tintColor={colors.accent} />}
        ListHeaderComponent={
          <View style={{ gap: 8 }}>
            <T medium style={{ fontSize: 18 }}>{t("jobsTitle")}</T>
            {offline && <T style={[s.banner, { color: colors.amber }]}>{t("offlineCached")}</T>}
            {queue.length > 0 && (
              <Pressable onPress={() => syncQueue()} style={s.queue}>
                <Ionicons name="cloud-offline" size={18} color={colors.amber} />
                <T medium style={{ color: colors.amber, flex: 1 }}>{t("jobsQueued", { n: queue.length })}</T>
              </Pressable>
            )}
          </View>
        }
        ListEmptyComponent={!loading ? <T style={[s.muted, { textAlign: "center", marginTop: 24 }]}>{t("jobsEmpty")}</T> : undefined}
        renderItem={({ item: j, index }) => (
          <Pressable style={s.card} onPress={() => setActive(j)}>
            <View style={s.stop}>
              <T medium style={{ color: "#fff" }}>{index + 1}</T>
            </View>
            <View style={{ flex: 1, gap: 3 }}>
              <T medium>{emojiFor(j.category.icon)} {t(categoryKey(j.category.icon))}</T>
              <T style={s.muted} numberOfLines={1}>
                {j.neighbourhood ?? ""}{j.leg_m != null ? ` · ${t("legM", { n: Math.round(j.leg_m) })}` : ""}
              </T>
              <T style={s.muted}>{t("priorityN", { n: j.priority })}</T>
            </View>
            <Pressable onPress={() => directions(j)} hitSlop={8} accessibilityLabel={t("openNav")}>
              <Ionicons name="navigate-circle" size={34} color={colors.accent} />
            </Pressable>
          </Pressable>
        )}
      />

      <Modal visible={!!active} transparent animationType="slide" onRequestClose={close}>
        <KeyboardAvoidingView style={s.backdrop} behavior={Platform.OS === "ios" ? "padding" : undefined}>
          <View style={s.sheet}>
            {active && (
              <>
                <T medium style={{ fontSize: 20 }}>
                  {emojiFor(active.category.icon)} {t(categoryKey(active.category.icon))} #{active.id}
                </T>
                <T style={s.muted} numberOfLines={3}>{active.description || t("noDescription")}</T>
                <View style={s.pair}>
                  <View style={{ flex: 1, gap: 4 }}>
                    <T style={s.muted}>{t("before")}</T>
                    {active.photo_url && <Image source={{ uri: photoUrl(active.photo_url)! }} style={s.pic} />}
                  </View>
                  <View style={{ flex: 1, gap: 4 }}>
                    <T style={s.muted}>{t("after")}</T>
                    <Pressable onPress={takeAfter} style={[s.pic, s.picEmpty]}>
                      {after ? (
                        <Image source={{ uri: after }} style={StyleSheet.absoluteFill} />
                      ) : (
                        <Ionicons name="camera" size={28} color={colors.orange} />
                      )}
                    </Pressable>
                  </View>
                </View>
                <Input placeholder={t("crewCommentPh")} value={comment} onChangeText={setComment} maxLength={500} />
                <Button title={t("markFixed")} onPress={done} loading={busy} disabled={!after} />
                <View style={{ flexDirection: "row", gap: 10 }}>
                  <Button title={t("openNav")} variant="ghost" onPress={() => directions(active)} style={{ flex: 1 }} />
                  <Button title={t("cancel")} variant="ghost" onPress={close} style={{ flex: 1 }} />
                </View>
                <Pressable onPress={() => { const id = active.id; close(); router.push(`/report/${id}`); }}>
                  <T style={{ color: colors.accent, textAlign: "center" }}>#{active.id} →</T>
                </Pressable>
              </>
            )}
          </View>
        </KeyboardAvoidingView>
      </Modal>
    </View>
  );
}

const makeStyles = (c: Palette) =>
  StyleSheet.create({
    map: { height: 240, backgroundColor: c.surface },
    muted: { color: c.muted, fontSize: 13 },
    banner: { fontSize: 13 },
    queue: { flexDirection: "row", gap: 8, alignItems: "center", padding: 12, borderRadius: 12, backgroundColor: c.amber + "22" },
    card: { flexDirection: "row", alignItems: "center", gap: 12, padding: 12, borderRadius: 16, backgroundColor: c.surface, borderWidth: 1, borderColor: c.line },
    stop: { width: 30, height: 30, borderRadius: 15, backgroundColor: c.blue, alignItems: "center", justifyContent: "center" },
    backdrop: { flex: 1, justifyContent: "flex-end", backgroundColor: "#000a" },
    sheet: { backgroundColor: c.surface, padding: 20, paddingBottom: 36, borderTopLeftRadius: 24, borderTopRightRadius: 24, gap: 10 },
    pair: { flexDirection: "row", gap: 10 },
    pic: { width: "100%", aspectRatio: 4 / 3, borderRadius: 12, backgroundColor: c.surface2, overflow: "hidden" },
    picEmpty: { alignItems: "center", justifyContent: "center", borderWidth: 1.5, borderStyle: "dashed", borderColor: c.orange },
  });
