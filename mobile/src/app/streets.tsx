import Ionicons from "@expo/vector-icons/Ionicons";
import { useFocusEffect } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, Alert, KeyboardAvoidingView, Platform, Pressable, RefreshControl, ScrollView, StyleSheet, View } from "react-native";
import { Button, Input, T } from "../components/ui";
import { api, type Adoption, type Place } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useI18n } from "../lib/i18n";
import { useStyles, useTheme, type Palette } from "../lib/theme";

/** Adopt a street: hear about every new problem on it; a school or business can adopt it under its name. */
export default function Streets() {
  const { user } = useAuth();
  const { colors } = useTheme();
  const { t, tErr } = useI18n();
  const s = useStyles(makeStyles);
  const [mine, setMine] = useState<Adoption[] | null>(null);
  const [q, setQ] = useState("");
  const [places, setPlaces] = useState<Place[] | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const [sponsor, setSponsor] = useState("");
  const [searching, setSearching] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setMine(await api.myStreets());
    } catch (e) {
      Alert.alert("MendMap", tErr((e as Error).message));
    } finally {
      setLoading(false);
    }
  }, [tErr]);
  useFocusEffect(useCallback(() => void load(), [load]));

  const type = (v: string) => {
    setQ(v);
    setPicked(null);
    clearTimeout(timer.current);
    if (v.trim().length < 2) {
      setPlaces(null);
      setSearching(false);
      return;
    }
    setSearching(true);
    timer.current = setTimeout(async () => {
      try {
        // Only streets can be adopted.
        setPlaces((await api.searchStreets(v.trim())).filter((p) => p.kind === "street"));
      } catch {
        setPlaces([]);
      } finally {
        setSearching(false);
      }
    }, 350);
  };

  const adopt = async () => {
    const street = picked ?? q.trim();
    if (street.length < 2) return;
    setBusy(true);
    try {
      await api.adopt(street, sponsor.trim() || null);
      setQ("");
      setPicked(null);
      setPlaces(null);
      setSponsor("");
      await load();
    } catch (e) {
      Alert.alert("MendMap", tErr((e as Error).message));
    } finally {
      setBusy(false);
    }
  };

  const remove = (a: Adoption) =>
    Alert.alert(a.street, t("stRemove") + "?", [
      { text: t("cancel"), style: "cancel" },
      {
        text: t("stRemove"), style: "destructive",
        onPress: async () => {
          try {
            await api.unadopt(a.id);
            await load();
          } catch (e) {
            Alert.alert("MendMap", tErr((e as Error).message));
          }
        },
      },
    ]);

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
      <ScrollView contentContainerStyle={s.page} keyboardShouldPersistTaps="handled"
        refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={colors.accent} />}>
        <View style={s.hero}>
          <T style={{ fontSize: 30 }}>💚</T>
          <T style={s.heroText}>{t("stIntro")}</T>
        </View>

        {mine?.length === 0 && <T style={[s.muted, { textAlign: "center", padding: 8 }]}>{t("stNone")}</T>}
        {mine?.map((a) => (
          <View key={a.id} style={s.card}>
            <View style={s.icon}><Ionicons name="trail-sign" size={20} color="#fff" /></View>
            <View style={{ flex: 1, gap: 2 }}>
              <T medium style={{ fontSize: 16 }}>{a.street}</T>
              {!!a.sponsor && <T style={s.muted}>{a.sponsor}</T>}
              <T style={[s.muted, a.open > 0 && { color: colors.orange }]}>{a.open > 0 ? t("stOpen", { n: a.open }) : t("stAllGood")}</T>
            </View>
            <Pressable onPress={() => remove(a)} hitSlop={10}>
              <Ionicons name="close-circle-outline" size={22} color={colors.muted} />
            </Pressable>
          </View>
        ))}

        {user?.role !== "crew" && (mine?.length ?? 0) < 5 && (
          <View style={[s.card, { flexDirection: "column", alignItems: "stretch" }]}>
            <T medium style={{ fontSize: 16 }}>{t("stAdd")}</T>
            <View style={s.searchBox}>
              <Ionicons name="search" size={18} color={colors.muted} />
              <Input style={s.searchInput} value={q} onChangeText={type} placeholder={t("streetPlaceholder")} autoCorrect={false} />
              {searching && <ActivityIndicator size="small" color={colors.accent} />}
            </View>
            {places && !picked && places.length > 0 && (
              <View style={s.suggestions}>
                {places.map((p, i) => (
                  <Pressable key={`${p.name}-${i}`} style={[s.suggestion, i > 0 && s.line]}
                    onPress={() => { setPicked(p.name); setQ(p.name); setPlaces(null); }}>
                    <Ionicons name="trail-sign-outline" size={18} color={colors.accent} />
                    <View style={{ flex: 1 }}>
                      <T medium numberOfLines={1}>{p.name}</T>
                      {!!p.detail && <T style={s.muted} numberOfLines={1}>{p.detail}</T>}
                    </View>
                  </Pressable>
                ))}
              </View>
            )}
            <Input value={sponsor} onChangeText={setSponsor} placeholder={t("stSponsor")} maxLength={80} />
            <Button title={t("stAdd")} variant="orange" onPress={adopt} loading={busy} disabled={q.trim().length < 2}
              icon={<Ionicons name="heart" size={18} color="#fff" />} />
          </View>
        )}
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const makeStyles = (c: Palette) =>
  StyleSheet.create({
    page: { padding: 16, gap: 10, paddingBottom: 60 },
    hero: { flexDirection: "row", alignItems: "center", gap: 12, padding: 14, borderRadius: 18, backgroundColor: c.surface2 },
    heroText: { flex: 1, fontSize: 14 },
    card: { flexDirection: "row", alignItems: "center", gap: 12, padding: 12, borderRadius: 16, backgroundColor: c.surface, borderWidth: 1, borderColor: c.line },
    icon: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center", backgroundColor: c.fixed },
    muted: { color: c.muted, fontSize: 13 },
    searchBox: { flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: 12, borderRadius: 14, backgroundColor: c.surface2, borderWidth: 1, borderColor: c.line },
    searchInput: { flex: 1, borderWidth: 0, backgroundColor: "transparent", paddingHorizontal: 0 },
    suggestions: { borderRadius: 14, backgroundColor: c.surface2, borderWidth: 1, borderColor: c.line, overflow: "hidden" },
    suggestion: { flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: 12, paddingVertical: 10 },
    line: { borderTopWidth: 1, borderTopColor: c.line },
  });
