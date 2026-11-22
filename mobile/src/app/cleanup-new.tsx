import Ionicons from "@expo/vector-icons/Ionicons";
import { router, useLocalSearchParams } from "expo-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { ActivityIndicator, Alert, KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, View } from "react-native";
import { Button, Input, T } from "../components/ui";
import { api, type Place } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useI18n } from "../lib/i18n";
import { useStyles, useTheme, type Palette } from "../lib/theme";

const DAYS_AHEAD = 21;
const HOURS = [8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19];

/** Organise a clean-up day: what, where (street search), which neighbourhood, day and time. */
export default function NewCleanup() {
  const params = useLocalSearchParams<{ room?: string }>();
  const { user } = useAuth();
  const { colors } = useTheme();
  const { t, tErr, locale } = useI18n();
  const s = useStyles(makeStyles);
  const [rooms, setRooms] = useState<string[]>(["city"]);
  const [room, setRoom] = useState<string>(params.room ?? user?.neighbourhood ?? "city");
  const [title, setTitle] = useState("");
  const [details, setDetails] = useState("");
  const [place, setPlace] = useState("");
  const [coords, setCoords] = useState<{ latitude: number; longitude: number } | null>(null);
  const [places, setPlaces] = useState<Place[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [day, setDay] = useState(1); // tomorrow
  const [hour, setHour] = useState(10);
  const [busy, setBusy] = useState(false);
  const [now] = useState(() => new Date()); // when the form opened
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    api.neighbourhoods().then((n) => setRooms(["city", ...n])).catch(() => {});
    return () => clearTimeout(timer.current);
  }, []);

  const days = useMemo(() => {
    const out: { i: number; label: string }[] = [];
    const base = new Date();
    for (let i = 0; i <= DAYS_AHEAD; i++) {
      const d = new Date(base.getFullYear(), base.getMonth(), base.getDate() + i);
      let label: string;
      try {
        label = d.toLocaleDateString(locale, { weekday: "short", day: "numeric", month: "short" });
      } catch {
        label = d.toDateString();
      }
      out.push({ i, label: i === 0 ? t("cuToday") : i === 1 ? t("cuTomorrow") : label });
    }
    return out;
  }, [locale, t]);

  const typePlace = (v: string) => {
    setPlace(v);
    setCoords(null);
    clearTimeout(timer.current);
    if (v.trim().length < 2) {
      setPlaces(null);
      setSearching(false);
      return;
    }
    setSearching(true);
    timer.current = setTimeout(async () => {
      try {
        setPlaces(await api.searchStreets(v.trim()));
      } catch {
        setPlaces([]);
      } finally {
        setSearching(false);
      }
    }, 350);
  };

  const pick = (p: Place) => {
    setPlace(p.detail && p.kind === "place" ? `${p.name}, ${p.detail}` : p.name);
    setCoords({ latitude: p.latitude, longitude: p.longitude });
    setPlaces(null);
  };

  const startsAt = () => {
    return new Date(now.getFullYear(), now.getMonth(), now.getDate() + day, hour, 0, 0);
  };
  const tooSoon = startsAt().getTime() < now.getTime() + 30 * 60_000;
  const ready = title.trim().length >= 3 && place.trim().length >= 2 && !tooSoon;

  const create = async () => {
    if (!ready) return;
    setBusy(true);
    try {
      const e = await api.createEvent({
        room, title: title.trim(), details: details.trim() || undefined, place: place.trim(),
        starts_at: startsAt().toISOString(), ...(coords ?? {}),
      });
      router.replace(`/cleanup/${e.id}`);
    } catch (err) {
      Alert.alert("MendMap", tErr((err as Error).message));
    } finally {
      setBusy(false);
    }
  };

  const chip = (on: boolean, label: string, onPress: () => void, key: string | number, disabled = false) => (
    <Pressable key={key} onPress={onPress} disabled={disabled}
      style={[s.chip, on && s.chipOn, disabled && { opacity: 0.35 }]}>
      <T medium={on} style={on ? { color: "#fff" } : undefined}>{label}</T>
    </Pressable>
  );

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
      <ScrollView contentContainerStyle={s.page} keyboardShouldPersistTaps="handled">
        <T medium style={s.label}>{t("cuWhat")}</T>
        <Input value={title} onChangeText={setTitle} placeholder={t("cuWhatPh")} maxLength={120} />

        <T medium style={s.label}>{t("cuWhere")}</T>
        <View style={s.searchBox}>
          <Ionicons name="location" size={18} color={colors.muted} />
          <Input style={s.searchInput} value={place} onChangeText={typePlace} placeholder={t("streetPlaceholder")} autoCorrect={false} />
          {searching && <ActivityIndicator size="small" color={colors.accent} />}
        </View>
        {places && places.length > 0 && (
          <View style={s.suggestions}>
            {places.map((p, i) => (
              <Pressable key={`${p.name}-${i}`} onPress={() => pick(p)} style={[s.suggestion, i > 0 && s.line]}>
                <Ionicons name={p.kind === "street" ? "trail-sign-outline" : "location-outline"} size={18} color={colors.accent} />
                <View style={{ flex: 1 }}>
                  <T medium numberOfLines={1}>{p.name}</T>
                  {!!p.detail && <T style={s.muted} numberOfLines={1}>{p.detail}</T>}
                </View>
              </Pressable>
            ))}
          </View>
        )}

        <T medium style={s.label}>{t("cuRoom")}</T>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chips}>
          {rooms.map((r) => chip(room === r, r === "city" ? `🏙️ ${t("chatCity")}` : r, () => setRoom(r), r))}
        </ScrollView>

        <T medium style={s.label}>{t("cuWhen")}</T>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chips}>
          {days.map((d) => chip(day === d.i, d.label, () => setDay(d.i), d.i))}
        </ScrollView>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chips}>
          {HOURS.map((h) => {
            const past = day === 0 && h <= now.getHours();
            return chip(hour === h, `${String(h).padStart(2, "0")}:00`, () => setHour(h), h, past);
          })}
        </ScrollView>

        <T medium style={s.label}>{t("cuDetails")}</T>
        <Input value={details} onChangeText={setDetails} multiline maxLength={1000}
          style={{ height: 90, paddingTop: 12, textAlignVertical: "top" }} />

        <Button title={t("cuCreate")} variant="orange" onPress={create} loading={busy} disabled={!ready}
          icon={<Ionicons name="megaphone" size={18} color="#fff" />} style={{ marginTop: 10 }} />
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const makeStyles = (c: Palette) =>
  StyleSheet.create({
    page: { padding: 16, gap: 8, paddingBottom: 60 },
    label: { marginTop: 10, fontSize: 15 },
    muted: { color: c.muted, fontSize: 13 },
    chips: { gap: 8, paddingVertical: 2 },
    chip: { paddingHorizontal: 14, paddingVertical: 9, borderRadius: 20, backgroundColor: c.surface, borderWidth: 1, borderColor: c.line },
    chipOn: { backgroundColor: c.orange, borderColor: c.orange },
    searchBox: { flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: 12, borderRadius: 14, backgroundColor: c.surface, borderWidth: 1, borderColor: c.line },
    searchInput: { flex: 1, borderWidth: 0, backgroundColor: "transparent", paddingHorizontal: 0 },
    suggestions: { borderRadius: 14, backgroundColor: c.surface, borderWidth: 1, borderColor: c.line, overflow: "hidden" },
    suggestion: { flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: 12, paddingVertical: 10 },
    line: { borderTopWidth: 1, borderTopColor: c.line },
  });
