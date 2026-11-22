import Ionicons from "@expo/vector-icons/Ionicons";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { router, useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { Pressable, RefreshControl, ScrollView, StyleSheet, View } from "react-native";
import Animated, { FadeInDown } from "react-native-reanimated";
import { T, useTimeAgo } from "../../components/ui";
import { api, type ChatRoom } from "../../lib/api";
import { SEEN_KEY } from "../../lib/chat";
import { useI18n } from "../../lib/i18n";
import { useStyles, useTheme, type Palette } from "../../lib/theme";

/** Community chat rooms: the whole city first, then the user's neighbourhood, then the others. */
export default function ChatRooms() {
  const { colors } = useTheme();
  const { t, tErr } = useI18n();
  const ago = useTimeAgo();
  const s = useStyles(makeStyles);
  const [rooms, setRooms] = useState<ChatRoom[] | null>(null);
  const [seen, setSeen] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const list = await api.chatRooms();
      const pairs = await AsyncStorage.multiGet(list.map((r) => SEEN_KEY(r.id)));
      setSeen(Object.fromEntries(pairs.map(([k, v], i) => [list[i].id, Number(v ?? 0)])));
      setRooms(list);
      setError("");
    } catch (e) {
      setError(tErr((e as Error).message));
    } finally {
      setLoading(false);
    }
  }, [tErr]);

  // Refresh when the tab is opened, and every 15 seconds while it is open.
  useFocusEffect(
    useCallback(() => {
      void load();
      const timer = setInterval(() => void load(), 15_000);
      return () => clearInterval(timer);
    }, [load]),
  );

  const city = rooms?.[0];
  const mine = rooms?.filter((r) => r.mine) ?? [];
  const others = rooms?.slice(1).filter((r) => !r.mine) ?? [];

  const row = (r: ChatRoom, i: number) => {
    const unread = r.last_id != null && r.last_id > (seen[r.id] ?? 0);
    const isCity = r.id === "city";
    return (
      <Animated.View key={r.id} entering={FadeInDown.delay(30 * i)}>
        <Pressable
          style={({ pressed }) => [s.room, pressed && { opacity: 0.7 }]}
          onPress={() => router.push({ pathname: "/chat/[room]", params: { room: r.id, name: r.name } })}
        >
          <View style={[s.icon, { backgroundColor: isCity ? colors.blue : r.mine ? colors.orange : colors.surface2 }]}>
            <Ionicons name={isCity ? "business" : r.mine ? "home" : "people"} size={22} color={isCity || r.mine ? "#fff" : colors.text} />
          </View>
          <View style={{ flex: 1, gap: 2 }}>
            <View style={s.line}>
              <T medium style={{ fontSize: 16, flex: 1 }} numberOfLines={1}>
                {isCity ? `${r.name} · ${t("chatCity")}` : r.name}
              </T>
              {!!r.last_at && <T style={s.time}>{ago(r.last_at)}</T>}
            </View>
            <View style={s.line}>
              <T style={[s.muted, { flex: 1 }, unread && { color: colors.text }]} numberOfLines={1}>
                {r.last_text ? `${r.last_name}: ${r.last_text}` : t("chatNoMessages")}
              </T>
              {r.today > 0 && <T style={s.today}>{t("chatToday", { n: r.today })}</T>}
              {unread && <View style={s.dot} />}
            </View>
          </View>
        </Pressable>
      </Animated.View>
    );
  };

  return (
    <ScrollView
      contentContainerStyle={s.page}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={colors.accent} />}
    >
      <View style={s.hero}>
        <T style={{ fontSize: 30 }}>💬</T>
        <T style={s.heroText}>{t("chatIntro")}</T>
      </View>
      {!!error && <T style={{ color: colors.danger }}>{error}</T>}
      {city && row(city, 0)}
      {mine.length > 0 && <T medium style={s.section}>{t("chatYourArea")}</T>}
      {mine.map((r, i) => row(r, i + 1))}
      {others.length > 0 && <T medium style={s.section}>{t("chatAreas")}</T>}
      {others.map((r, i) => row(r, i + 2))}
    </ScrollView>
  );
}

const makeStyles = (c: Palette) =>
  StyleSheet.create({
    page: { padding: 16, gap: 10, paddingBottom: 40 },
    hero: { flexDirection: "row", alignItems: "center", gap: 12, padding: 14, borderRadius: 18, backgroundColor: c.surface2 },
    heroText: { flex: 1, color: c.text, fontSize: 14 },
    section: { marginTop: 8, color: c.muted, fontSize: 13, textTransform: "uppercase", letterSpacing: 0.6 },
    room: { flexDirection: "row", alignItems: "center", gap: 12, padding: 12, borderRadius: 16, backgroundColor: c.surface, borderWidth: 1, borderColor: c.line },
    icon: { width: 46, height: 46, borderRadius: 23, alignItems: "center", justifyContent: "center" },
    line: { flexDirection: "row", alignItems: "center", gap: 8 },
    muted: { color: c.muted, fontSize: 14 },
    time: { color: c.muted, fontSize: 12 },
    today: { color: c.accent, fontSize: 12 },
    dot: { width: 10, height: 10, borderRadius: 5, backgroundColor: c.orange },
  });
