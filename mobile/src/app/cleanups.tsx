import Ionicons from "@expo/vector-icons/Ionicons";
import { router, Stack, useFocusEffect, useLocalSearchParams } from "expo-router";
import { useCallback, useState } from "react";
import { Pressable, RefreshControl, ScrollView, StyleSheet, View } from "react-native";
import Animated, { FadeInDown } from "react-native-reanimated";
import { Button, T } from "../components/ui";
import { api, type CleanupEvent } from "../lib/api";
import { useAuth } from "../lib/auth";
import { dayBox, fmtWhen } from "../lib/events";
import { useI18n } from "../lib/i18n";
import { useStyles, useTheme, type Palette } from "../lib/theme";

/** Clean-up days: upcoming ones (for one room, or everywhere), then past ones. */
export default function Cleanups() {
  const { room } = useLocalSearchParams<{ room?: string }>();
  const { user } = useAuth();
  const { colors } = useTheme();
  const { t, tErr, locale } = useI18n();
  const s = useStyles(makeStyles);
  const [upcoming, setUpcoming] = useState<CleanupEvent[] | null>(null);
  const [past, setPast] = useState<CleanupEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [u, p] = await Promise.all([api.events(room), api.events(room, true)]);
      setUpcoming(u);
      setPast(p.slice(0, 10));
      setError("");
    } catch (e) {
      setError(tErr((e as Error).message));
    } finally {
      setLoading(false);
    }
  }, [room, tErr]);
  useFocusEffect(useCallback(() => void load(), [load]));

  const where = (r: string) => (r === "city" ? "Prishtina" : r);

  const card = (e: CleanupEvent, i: number) => {
    const box = dayBox(e.starts_at, locale);
    return (
      <Animated.View key={e.id} entering={FadeInDown.delay(40 * i)}>
        <Pressable style={({ pressed }) => [s.card, pressed && { opacity: 0.7 }, e.cancelled && { opacity: 0.5 }]}
          onPress={() => router.push(`/cleanup/${e.id}`)}>
          <View style={s.dateBox}>
            <T style={s.wd}>{box.wd}</T>
            <T medium style={s.day}>{box.day}</T>
          </View>
          <View style={{ flex: 1, gap: 3 }}>
            <T medium style={{ fontSize: 16 }} numberOfLines={2}>{e.title}</T>
            <T style={s.muted} numberOfLines={1}>🕘 {fmtWhen(e.starts_at, locale, t)} · {where(e.room)}</T>
            <T style={s.muted} numberOfLines={1}>📍 {e.place}</T>
          </View>
          <View style={{ alignItems: "flex-end", gap: 4 }}>
            {e.cancelled ? <T style={[s.muted, { color: colors.danger }]}>{t("cuCancelled")}</T>
              : e.done ? <T style={[s.muted, { color: colors.fixed }]}>{t("cuDone")}</T>
                : <T medium style={{ color: colors.accent }}>{t("cuGoing", { n: e.going })}</T>}
            {e.me_going && !e.cancelled && <Ionicons name="checkmark-circle" size={18} color={colors.fixed} />}
          </View>
        </Pressable>
      </Animated.View>
    );
  };

  return (
    <ScrollView contentContainerStyle={s.page}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={colors.accent} />}>
      <Stack.Screen options={{ title: room ? `${t("cuTitle")} · ${where(room)}` : t("cuTitle") }} />
      <View style={s.hero}>
        <T style={{ fontSize: 30 }}>🧹</T>
        <T style={s.heroText}>{t("cuIntro")}</T>
      </View>
      {user?.role !== "crew" && (
        <Button title={t("cuNew")} variant="orange"
          onPress={() => router.push({ pathname: "/cleanup-new", params: room ? { room } : {} })}
          icon={<Ionicons name="add-circle" size={20} color="#fff" />} />
      )}
      {!!error && <T style={{ color: colors.danger }}>{error}</T>}
      {upcoming?.length === 0 && <T style={[s.muted, { textAlign: "center", padding: 16 }]}>{t("cuNone")}</T>}
      {upcoming?.map(card)}
      {past.length > 0 && <T medium style={s.section}>{t("cuPast")}</T>}
      {past.map((e, i) => card(e, i + (upcoming?.length ?? 0)))}
    </ScrollView>
  );
}

const makeStyles = (c: Palette) =>
  StyleSheet.create({
    page: { padding: 16, gap: 10, paddingBottom: 40 },
    hero: { flexDirection: "row", alignItems: "center", gap: 12, padding: 14, borderRadius: 18, backgroundColor: c.surface2 },
    heroText: { flex: 1, fontSize: 14 },
    section: { marginTop: 10, color: c.muted, fontSize: 13, textTransform: "uppercase", letterSpacing: 0.6 },
    card: { flexDirection: "row", alignItems: "center", gap: 12, padding: 12, borderRadius: 16, backgroundColor: c.surface, borderWidth: 1, borderColor: c.line },
    dateBox: { width: 52, height: 56, borderRadius: 12, alignItems: "center", justifyContent: "center", backgroundColor: c.orange },
    wd: { color: "#fff", fontSize: 11, letterSpacing: 0.5 },
    day: { color: "#fff", fontSize: 22, lineHeight: 26 },
    muted: { color: c.muted, fontSize: 13 },
  });
