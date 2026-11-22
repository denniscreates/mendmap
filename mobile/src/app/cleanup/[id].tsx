import Ionicons from "@expo/vector-icons/Ionicons";
import { router, Stack, useFocusEffect, useLocalSearchParams } from "expo-router";
import { useCallback, useState } from "react";
import { ActivityIndicator, Alert, Linking, Pressable, RefreshControl, ScrollView, StyleSheet, View } from "react-native";
import { Button, T } from "../../components/ui";
import { api, type CleanupEvent } from "../../lib/api";
import { fmtWhen } from "../../lib/events";
import { useI18n } from "../../lib/i18n";
import { useStyles, useTheme, type Palette } from "../../lib/theme";

/** One clean-up day: details, "I'm coming", and for the organiser: who came (badges) or cancel. */
export default function CleanupDay() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { colors } = useTheme();
  const { t, tErr, locale } = useI18n();
  const s = useStyles(makeStyles);
  const [e, setE] = useState<CleanupEvent | null>(null);
  const [came, setCame] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const show = useCallback((ev: CleanupEvent) => {
    setE(ev);
    // Before anything is saved, everyone who said they'd come is ticked.
    setCame(new Set(ev.people.filter((p) => (ev.done ? p.attended : true)).map((p) => p.user_id)));
  }, []);

  const load = useCallback(async () => {
    try {
      show(await api.event(Number(id)));
      setError("");
    } catch (err) {
      setError(tErr((err as Error).message));
    }
  }, [id, show, tErr]);
  useFocusEffect(useCallback(() => void load(), [load]));

  const run = async (job: () => Promise<CleanupEvent>, done?: string) => {
    setBusy(true);
    try {
      show(await job());
      if (done) Alert.alert("MendMap", done);
    } catch (err) {
      Alert.alert("MendMap", tErr((err as Error).message));
    } finally {
      setBusy(false);
    }
  };

  if (!e)
    return (
      <View style={s.center}>
        {error ? <T style={{ color: colors.danger }}>{error}</T> : <ActivityIndicator color={colors.accent} />}
      </View>
    );

  const where = e.room === "city" ? "Prishtina" : e.room;
  const open = !e.cancelled && !e.past;
  const openMap = () => {
    if (e.latitude == null || e.longitude == null) return;
    const q = `${e.latitude},${e.longitude}`;
    void Linking.openURL(`https://www.google.com/maps/search/?api=1&query=${q}`);
  };

  return (
    <ScrollView contentContainerStyle={s.page} refreshControl={<RefreshControl refreshing={false} onRefresh={load} tintColor={colors.accent} />}>
      <Stack.Screen options={{ title: t("cuTitle") }} />
      <View style={s.hero}>
        <T style={{ fontSize: 36 }}>🧹</T>
        <T medium style={s.title}>{e.title}</T>
        <T style={s.heroText}>{t("cuOrganiser", { name: e.organiser_name })} · {where}</T>
        {e.cancelled && <T medium style={s.badge}>{t("cuCancelled")}</T>}
        {e.done && <T medium style={s.badge}>{t("cuDone")}</T>}
      </View>

      <View style={s.card}>
        <View style={s.row}><Ionicons name="time" size={20} color={colors.accent} /><T medium style={{ flex: 1 }}>{fmtWhen(e.starts_at, locale, t)}</T></View>
        <Pressable style={s.row} onPress={openMap} disabled={e.latitude == null}>
          <Ionicons name="location" size={20} color={colors.accent} />
          <T medium style={{ flex: 1 }}>{e.place}</T>
          {e.latitude != null && <Ionicons name="open-outline" size={16} color={colors.muted} />}
        </Pressable>
        <View style={s.row}><Ionicons name="people" size={20} color={colors.accent} /><T medium>{t("cuGoing", { n: e.going })}</T></View>
        {!!e.details && <T style={s.details}>{e.details}</T>}
      </View>

      {open && !e.mine && (e.me_going
        ? <Button title={t("cuNotGoing")} variant="ghost" loading={busy} onPress={() => run(() => api.rsvp(e.id, false))} />
        : <Button title={t("cuImGoing")} variant="orange" loading={busy} onPress={() => run(() => api.rsvp(e.id, true))}
          icon={<Ionicons name="hand-right" size={18} color="#fff" />} />)}
      {open && !e.mine && e.me_going && <T style={[s.muted, { textAlign: "center" }]}>{t("cuYoureGoing")}</T>}

      {e.people.length > 0 && (
        <View style={s.card}>
          <T medium style={{ fontSize: 16 }}>{e.past && !e.cancelled ? t("cuWhoCame") : t("cuPeople")}</T>
          {e.past && !e.cancelled && <T style={s.muted}>{t("cuWhoCameHint")}</T>}
          {e.people.map((p) => {
            const on = came.has(p.user_id);
            const canTick = e.past && !e.cancelled;
            return (
              <Pressable key={p.user_id} disabled={!canTick} style={s.person}
                onPress={() => setCame((cur) => {
                  const next = new Set(cur);
                  if (next.has(p.user_id)) next.delete(p.user_id);
                  else next.add(p.user_id);
                  return next;
                })}>
                {canTick
                  ? <Ionicons name={on ? "checkbox" : "square-outline"} size={22} color={on ? colors.fixed : colors.muted} />
                  : <Ionicons name="person-circle" size={22} color={colors.muted} />}
                <T style={{ flex: 1 }}>{p.name}</T>
                {e.done && p.attended && <T style={{ color: colors.fixed }}>🛠️ +1</T>}
              </Pressable>
            );
          })}
          {e.past && !e.cancelled && (
            <Button title={t("cuSaveAttendance")} loading={busy}
              onPress={() => run(() => api.attendance(e.id, [...came]), t("cuSaved"))} />
          )}
        </View>
      )}

      {open && e.mine && (
        <Button title={t("cuCancel")} variant="ghost" loading={busy}
          onPress={() => Alert.alert(t("cuCancel"), t("cuCancelAsk"), [
            { text: t("cancel"), style: "cancel" },
            { text: t("cuCancel"), style: "destructive", onPress: () => void run(() => api.cancelEvent(e.id)) },
          ])} />
      )}
      <Pressable onPress={() => router.push({ pathname: "/chat/[room]", params: { room: e.room, name: where } })} style={s.chatLink}>
        <Ionicons name="chatbubbles-outline" size={18} color={colors.accent} />
        <T medium style={{ color: colors.accent }}>{t("chatTitle")} · {where}</T>
      </Pressable>
    </ScrollView>
  );
}

const makeStyles = (c: Palette) =>
  StyleSheet.create({
    center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 30 },
    page: { padding: 16, gap: 12, paddingBottom: 40 },
    hero: { alignItems: "center", gap: 6, padding: 20, borderRadius: 20, backgroundColor: c.orange },
    title: { color: "#fff", fontSize: 22, textAlign: "center" },
    heroText: { color: "#fff", opacity: 0.92, textAlign: "center" },
    badge: { color: c.orange, backgroundColor: "#fff", paddingHorizontal: 10, paddingVertical: 3, borderRadius: 10, overflow: "hidden", marginTop: 4 },
    card: { gap: 12, padding: 14, borderRadius: 16, backgroundColor: c.surface, borderWidth: 1, borderColor: c.line },
    row: { flexDirection: "row", alignItems: "center", gap: 10 },
    details: { color: c.text, fontSize: 15, lineHeight: 21 },
    muted: { color: c.muted, fontSize: 13 },
    person: { flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 4 },
    chatLink: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, padding: 10 },
  });
