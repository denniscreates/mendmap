import Ionicons from "@expo/vector-icons/Ionicons";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { router, Stack, useFocusEffect, useLocalSearchParams } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Image,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  TextInput,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { StatusPill, T } from "../../components/ui";
import { api, photoUrl, type ChatMessage } from "../../lib/api";
import { fmtWhen } from "../../lib/events";
import { useAuth } from "../../lib/auth";
import { SEEN_KEY } from "../../lib/chat";
import { useI18n } from "../../lib/i18n";
import { fonts, useStyles, useTheme, type Palette } from "../../lib/theme";

const POLL_MS = 4000;
const PAGE = 50;

/** One chat room. New messages arrive by polling every few seconds while the screen is open. */
export default function ChatRoomScreen() {
  const { room, name, report, reportTitle } = useLocalSearchParams<{ room: string; name?: string; report?: string; reportTitle?: string }>();
  const { user } = useAuth();
  const { colors } = useTheme();
  const { t, tErr, lang, locale } = useI18n();
  const insets = useSafeAreaInsets();
  const s = useStyles(makeStyles);
  const [msgs, setMsgs] = useState<ChatMessage[] | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [attached, setAttached] = useState<{ id: number; title: string } | null>(
    report ? { id: Number(report), title: reportTitle ?? `#${report}` } : null,
  );
  // Translations the user opened: id -> translated text (null while loading).
  const [shown, setShown] = useState<Record<number, string | null>>({});
  const latest = useRef<ChatMessage[]>([]);
  useEffect(() => {
    latest.current = msgs ?? []; // read by the poller
  }, [msgs]);

  const title = room === "city" ? `${name ?? "Prishtina"} · ${t("chatCity")}` : (name ?? room);

  const merge = useCallback((more: ChatMessage[]) => {
    if (!more.length) return;
    setMsgs((cur) => {
      const have = new Set((cur ?? []).map((m) => m.id));
      return [...(cur ?? []), ...more.filter((m) => !have.has(m.id))].sort((a, b) => a.id - b.id);
    });
  }, []);

  // First load, then poll for new and removed messages while the screen is open.
  useFocusEffect(
    useCallback(() => {
      let gone = false;
      const first = async () => {
        try {
          const list = await api.chatMessages(room);
          if (gone) return;
          setMsgs(list);
          setHasMore(list.length >= PAGE);
          setError("");
        } catch (e) {
          if (!gone) setError(tErr((e as Error).message));
        }
      };
      const poll = async () => {
        const cur = latest.current;
        if (!cur.length) return first();
        try {
          const [fresh, removed] = await Promise.all([
            api.chatMessages(room, { after: cur[cur.length - 1].id }),
            api.chatHidden(room, cur[0].id),
          ]);
          if (gone) return;
          merge(fresh);
          if (removed.length) setMsgs((m) => (m ?? []).filter((x) => !removed.includes(x.id)));
          setError("");
        } catch {
          // Offline for a moment: try again on the next tick.
        }
      };
      if (!latest.current.length) void first();
      else void poll();
      const timer = setInterval(() => void poll(), POLL_MS);
      return () => {
        gone = true;
        clearInterval(timer);
      };
    }, [room, merge, tErr]),
  );

  // Remember what was seen, for the unread dot on the room list.
  const lastId = msgs?.length ? msgs[msgs.length - 1].id : null;
  useEffect(() => {
    if (lastId != null) void AsyncStorage.setItem(SEEN_KEY(room), String(lastId));
  }, [room, lastId]);

  const loadEarlier = async () => {
    if (!msgs?.length || loadingMore) return;
    setLoadingMore(true);
    try {
      const older = await api.chatMessages(room, { before: msgs[0].id });
      merge(older);
      setHasMore(older.length >= PAGE);
    } catch (e) {
      Alert.alert("MendMap", tErr((e as Error).message));
    } finally {
      setLoadingMore(false);
    }
  };

  const send = async () => {
    const body = text.trim();
    if (!body || sending) return;
    setSending(true);
    try {
      const m = await api.chatSend(room, body, lang, attached?.id);
      merge([m]);
      setText("");
      setAttached(null);
    } catch (e) {
      // Blocked by the AI (the reason is already in the user's language), too fast, offline...
      Alert.alert("MendMap", tErr((e as Error).message));
    } finally {
      setSending(false);
    }
  };

  const actions = (m: ChatMessage) => {
    const canDelete = m.mine || user?.role === "admin";
    const buttons: { text: string; style?: "cancel" | "destructive"; onPress?: () => void }[] = [];
    if (!m.mine)
      buttons.push({
        text: t("chatReport"),
        onPress: async () => {
          try {
            const r = await api.chatFlag(m.id);
            if (r.hidden) setMsgs((cur) => (cur ?? []).filter((x) => x.id !== m.id));
            else Alert.alert("MendMap", t("chatReported"));
          } catch (e) {
            Alert.alert("MendMap", tErr((e as Error).message));
          }
        },
      });
    if (canDelete)
      buttons.push({
        text: t("chatDelete"),
        style: "destructive",
        onPress: async () => {
          try {
            await api.chatDelete(m.id);
            setMsgs((cur) => (cur ?? []).filter((x) => x.id !== m.id));
          } catch (e) {
            Alert.alert("MendMap", tErr((e as Error).message));
          }
        },
      });
    if (!buttons.length) return;
    buttons.push({ text: t("cancel"), style: "cancel" });
    Alert.alert(m.user_name, m.text.length > 120 ? m.text.slice(0, 120) + "…" : m.text, buttons);
  };

  const time = (iso: string) => {
    const d = new Date(iso.endsWith("Z") ? iso : iso + "Z");
    const today = new Date().toDateString() === d.toDateString();
    try {
      return today
        ? d.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" })
        : d.toLocaleString(locale, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
    } catch {
      return d.toLocaleTimeString();
    }
  };

  const translate = async (m: ChatMessage) => {
    if (m.id in shown) {
      setShown(({ [m.id]: _drop, ...rest }) => rest);
      return;
    }
    setShown((cur) => ({ ...cur, [m.id]: null }));
    try {
      const r = await api.chatTranslate(m.id, lang);
      setShown((cur) => ({ ...cur, [m.id]: r.text }));
    } catch (e) {
      setShown(({ [m.id]: _drop, ...rest }) => rest);
      Alert.alert("MendMap", tErr((e as Error).message));
    }
  };

  const rsvp = async (m: ChatMessage) => {
    if (!m.event) return;
    try {
      const e = await api.rsvp(m.event.id, !m.event.me_going);
      setMsgs((cur) => (cur ?? []).map((x) => (x.event?.id === e.id
        ? { ...x, event: { ...x.event, going: e.going, me_going: e.me_going, cancelled: e.cancelled } }
        : x)));
    } catch (err) {
      Alert.alert("MendMap", tErr((err as Error).message));
    }
  };

  const reversed = [...(msgs ?? [])].reverse();

  const translateLink = (m: ChatMessage, light = false) =>
    m.mine ? null : (
      <Pressable onPress={() => void translate(m)} hitSlop={6}>
        {shown[m.id] === null ? (
          <ActivityIndicator size="small" color={light ? "#fff" : colors.accent} style={{ alignSelf: "flex-start" }} />
        ) : (
          <T style={[s.translate, light && { color: "#ffffffcc" }]}>{m.id in shown ? t("chatOriginal") : t("chatTranslate")}</T>
        )}
      </Pressable>
    );

  const bubble = ({ item: m, index }: { item: ChatMessage; index: number }) => {
    // The list is upside down (newest at the bottom): the "previous" message is the next item.
    const prev = reversed[index + 1];
    const sameAuthor = prev && prev.user_id === m.user_id && prev.kind === "message";
    const body = shown[m.id] ?? m.text;

    if (m.kind === "announcement")
      return (
        <Pressable onLongPress={() => actions(m)} delayLongPress={350} style={s.announce}>
          <View style={s.author}>
            <Ionicons name="megaphone" size={16} color="#fff" />
            <T medium style={{ color: "#fff", flex: 1 }}>{t("chatAnnouncement")}</T>
            <T style={[s.time, { color: "#ffffffaa" }]}>{time(m.created_at)}</T>
          </View>
          <T style={s.mineText} selectable>{body}</T>
          {translateLink(m, true)}
        </Pressable>
      );

    if (m.kind === "event" && m.event) {
      const ev = m.event;
      return (
        <Pressable onPress={() => router.push(`/cleanup/${ev.id}`)} onLongPress={() => actions(m)} delayLongPress={350}
          style={[s.eventCard, ev.cancelled && { opacity: 0.55 }]}>
          <View style={s.author}>
            <T style={{ fontSize: 22 }}>🧹</T>
            <View style={{ flex: 1 }}>
              <T medium numberOfLines={2} style={{ fontSize: 16 }}>{ev.title}</T>
              <T style={s.eventMeta}>{m.user_name}</T>
            </View>
          </View>
          <T style={s.eventMeta}>🕘 {fmtWhen(ev.starts_at, locale, t)}</T>
          <T style={s.eventMeta} numberOfLines={1}>📍 {ev.place}</T>
          <View style={[s.author, { justifyContent: "space-between", marginTop: 4 }]}>
            <T medium style={{ color: colors.accent }}>{ev.cancelled ? t("cuCancelled") : t("cuGoing", { n: ev.going })}</T>
            {!ev.cancelled && !m.mine && (
              <Pressable onPress={() => void rsvp(m)} style={[s.rsvp, ev.me_going && { backgroundColor: colors.fixed }]}>
                <T medium style={{ color: "#fff", fontSize: 13 }}>{ev.me_going ? `✓ ${t("cuImGoing")}` : t("cuImGoing")}</T>
              </Pressable>
            )}
          </View>
        </Pressable>
      );
    }

    return (
      <View style={[s.msgRow, m.mine ? s.right : s.left, !sameAuthor && { marginTop: 10 }]}>
        <Pressable onLongPress={() => actions(m)} delayLongPress={350} style={[s.bubble, m.mine ? s.mine : s.theirs]}>
          {!m.mine && !sameAuthor && (
            <View style={s.author}>
              <T medium style={s.name}>{m.user_name}</T>
              {m.badge === "city" && <T style={[s.badge, { backgroundColor: colors.blue }]}>{t("chatBadgeCity")}</T>}
              {m.badge === "mjeshter" && <T style={[s.badge, { backgroundColor: colors.orange }]}>🛠️ {t("chatBadgeMj")}</T>}
            </View>
          )}
          {m.report && (
            <Pressable
              style={[s.reportCard, m.mine && { backgroundColor: "#ffffff22" }]}
              onPress={() => router.push(`/report/${m.report!.id}`)}
            >
              {m.report.photo_url ? (
                <Image source={{ uri: photoUrl(m.report.photo_url)! }} style={s.reportPhoto} />
              ) : (
                <View style={[s.reportPhoto, { alignItems: "center", justifyContent: "center" }]}>
                  <Ionicons name="location" size={20} color={colors.muted} />
                </View>
              )}
              <View style={{ flex: 1, gap: 4 }}>
                <T medium numberOfLines={2} style={m.mine ? { color: "#fff" } : undefined}>{m.report.title}</T>
                <StatusPill status={m.report.status} />
              </View>
            </Pressable>
          )}
          <T style={m.mine ? s.mineText : s.text} selectable>{body}</T>
          <View style={s.footer}>
            {translateLink(m)}
            <T style={[s.time, m.mine && { color: "#ffffffaa" }]}>{time(m.created_at)}</T>
          </View>
        </Pressable>
      </View>
    );
  };


  return (
    <KeyboardAvoidingView
      style={{ flex: 1, backgroundColor: colors.bg }}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
      keyboardVerticalOffset={Platform.OS === "ios" ? insets.top + 44 : 0}
    >
      <Stack.Screen
        options={{
          title,
          headerRight: () => (
            <Pressable onPress={() => router.push({ pathname: "/cleanups", params: { room } })} hitSlop={10} style={{ paddingHorizontal: 6 }}>
              <Ionicons name="leaf" size={22} color={colors.fixed} />
            </Pressable>
          ),
        }}
      />
      {msgs === null ? (
        <View style={s.center}>
          {error ? <T style={{ color: colors.danger, textAlign: "center" }}>{error}</T> : <ActivityIndicator color={colors.accent} />}
        </View>
      ) : (
        <FlatList
          inverted
          data={reversed}
          keyExtractor={(m) => String(m.id)}
          renderItem={bubble}
          contentContainerStyle={s.list}
          keyboardShouldPersistTaps="handled"
          ListEmptyComponent={
            <View style={[s.center, { transform: [{ scaleY: -1 }] }]}>
              <T style={{ fontSize: 40 }}>👋</T>
              <T style={s.muted}>{t("chatEmpty")}</T>
            </View>
          }
          ListFooterComponent={
            hasMore ? (
              <Pressable style={s.earlier} onPress={loadEarlier}>
                {loadingMore ? <ActivityIndicator color={colors.accent} /> : <T style={{ color: colors.accent }}>{t("chatEarlier")}</T>}
              </Pressable>
            ) : (
              <T style={[s.muted, s.rules]}>{t("chatRules")}</T>
            )
          }
        />
      )}

      <View style={[s.composer, { paddingBottom: Math.max(insets.bottom, 10) }]}>
        {attached && (
          <View style={s.attached}>
            <Ionicons name="attach" size={16} color={colors.accent} />
            <T style={{ flex: 1, fontSize: 13 }} numberOfLines={1}>{t("chatAttached")}: {attached.title}</T>
            <Pressable onPress={() => setAttached(null)} hitSlop={10}>
              <Ionicons name="close-circle" size={18} color={colors.muted} />
            </Pressable>
          </View>
        )}
        <View style={s.inputRow}>
          <TextInput
            style={s.input}
            value={text}
            onChangeText={setText}
            placeholder={t("chatPlaceholder")}
            placeholderTextColor={colors.muted}
            multiline
            maxLength={500}
          />
          <Pressable
            onPress={send}
            disabled={!text.trim() || sending}
            style={[s.send, (!text.trim() || sending) && { opacity: 0.45 }]}
          >
            {sending ? <ActivityIndicator color="#fff" size="small" /> : <Ionicons name="send" size={18} color="#fff" />}
          </Pressable>
        </View>
      </View>
    </KeyboardAvoidingView>
  );
}

const makeStyles = (c: Palette) =>
  StyleSheet.create({
    center: { flex: 1, alignItems: "center", justifyContent: "center", gap: 8, padding: 30 },
    list: { padding: 12, flexGrow: 1 },
    msgRow: { flexDirection: "row", marginTop: 3 },
    left: { justifyContent: "flex-start" },
    right: { justifyContent: "flex-end" },
    bubble: { maxWidth: "82%", paddingHorizontal: 12, paddingVertical: 8, borderRadius: 18, gap: 4 },
    mine: { backgroundColor: c.accent, borderBottomRightRadius: 6 },
    theirs: { backgroundColor: c.surface, borderWidth: 1, borderColor: c.line, borderBottomLeftRadius: 6 },
    author: { flexDirection: "row", alignItems: "center", gap: 6 },
    name: { fontSize: 13, color: c.accent },
    badge: { fontSize: 11, color: "#fff", paddingHorizontal: 6, paddingVertical: 1, borderRadius: 8, overflow: "hidden" },
    text: { fontSize: 15, color: c.text },
    mineText: { fontSize: 15, color: "#fff" },
    time: { fontSize: 11, color: c.muted, alignSelf: "flex-end", marginLeft: "auto" },
    footer: { flexDirection: "row", alignItems: "center", gap: 10 },
    translate: { fontSize: 12, color: c.accent },
    announce: { marginTop: 10, marginHorizontal: 4, padding: 12, gap: 6, borderRadius: 16, backgroundColor: c.blue },
    eventCard: { marginTop: 10, marginHorizontal: 4, padding: 12, gap: 4, borderRadius: 16, backgroundColor: c.surface, borderWidth: 2, borderColor: c.fixed },
    eventMeta: { fontSize: 13, color: c.muted },
    rsvp: { paddingHorizontal: 12, paddingVertical: 7, borderRadius: 14, backgroundColor: c.orange },
    muted: { color: c.muted, fontSize: 14, textAlign: "center" },
    rules: { paddingVertical: 14, fontSize: 12 },
    earlier: { alignItems: "center", paddingVertical: 14 },
    reportCard: { flexDirection: "row", alignItems: "center", gap: 10, padding: 8, borderRadius: 12, backgroundColor: c.surface2, minWidth: 220 },
    reportPhoto: { width: 52, height: 52, borderRadius: 10, backgroundColor: c.line },
    composer: { paddingHorizontal: 10, paddingTop: 8, gap: 6, backgroundColor: c.surface, borderTopWidth: 1, borderTopColor: c.line },
    attached: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 12, backgroundColor: c.surface2 },
    inputRow: { flexDirection: "row", alignItems: "flex-end", gap: 8 },
    input: {
      flex: 1, minHeight: 42, maxHeight: 120, paddingHorizontal: 14, paddingTop: 11, paddingBottom: 11, borderRadius: 21,
      backgroundColor: c.surface2, color: c.text, fontFamily: fonts.regular, fontSize: 15,
    },
    send: { width: 42, height: 42, borderRadius: 21, alignItems: "center", justifyContent: "center", backgroundColor: c.orange },
  });
