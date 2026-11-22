import Ionicons from "@expo/vector-icons/Ionicons";
import { router, useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { Pressable, RefreshControl, ScrollView, StyleSheet, View } from "react-native";
import Animated, { FadeInDown } from "react-native-reanimated";
import { Button, T } from "../components/ui";
import { api, type MjeshterMe, type MjeshterPublic } from "../lib/api";
import { useAuth } from "../lib/auth";
import { LEVEL_ICON } from "../lib/fixer";
import { useI18n, type TKey } from "../lib/i18n";
import { SKILL_ICON, SKILLS } from "../lib/mjeshtrit";
import { useStyles, useTheme, type Palette } from "../lib/theme";

/** Mjeshtrit: verified skilled volunteers who fix things when the city doesn't work (e.g. Sundays). */
export default function MjeshtritScreen() {
  const { user } = useAuth();
  const { colors } = useTheme();
  const { t, tErr } = useI18n();
  const s = useStyles(makeStyles);
  const [list, setList] = useState<MjeshterPublic[]>([]);
  const [me, setMe] = useState<MjeshterMe | null>(null);
  const [skill, setSkill] = useState<string | null>(null);
  const [sunday, setSunday] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [l, m] = await Promise.all([api.mjeshtrit(skill, sunday ? "sunday" : null), api.mjeshterMe().catch(() => null)]);
      setList(l);
      setMe(m);
      setError("");
    } catch (e) {
      setError(tErr((e as Error).message));
    } finally {
      setLoading(false);
    }
  }, [skill, sunday, tErr]);
  useFocusEffect(useCallback(() => void load(), [load]));

  const citizen = user?.role === "citizen";

  return (
    <ScrollView
      contentContainerStyle={s.page}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={colors.accent} />}
    >
      {/* What this is + my own status */}
      <Animated.View entering={FadeInDown} style={s.hero}>
        <T style={{ fontSize: 34 }}>🧰</T>
        <View style={{ flex: 1, gap: 4 }}>
          <T medium style={s.heroTitle}>{t("mjTitle")}</T>
          <T style={s.heroText}>{t("mjIntro")}</T>
        </View>
      </Animated.View>

      {citizen && !me && (
        <View style={s.card}>
          <T medium style={{ fontSize: 16 }}>🔧 {t("mjBecome")}</T>
          <T style={s.muted}>{t("mjBecomeBody")}</T>
          <Button title={t("mjSignUp")} variant="orange" onPress={() => router.push("/mjeshter-apply")} />
        </View>
      )}
      {me?.status === "approved" && (
        <View style={[s.card, { borderColor: colors.fixed }]}>
          <T medium style={{ fontSize: 16, color: colors.fixed }}>✓ {t("mjYouAre")}</T>
          <T style={s.muted}>
            {me.verified_skills.map((k) => `${SKILL_ICON[k]} ${t(`skill_${k}` as TKey)}`).join("  ·  ")}
          </T>
          <T style={s.muted}>{me.verified_by === "ai" ? t("mjVerifiedAi") : t("mjVerifiedCity")}</T>
          <Button title={t("mjSeeJobs")} variant="ghost" onPress={() => router.push("/fix")} />
        </View>
      )}
      {me?.status === "pending" && (
        <View style={[s.card, { borderColor: colors.amber }]}>
          <T medium style={{ fontSize: 16, color: colors.amber }}>⏳ {t("mjPending")}</T>
          <T style={s.muted}>{t("mjPendingBody")}</T>
          {!!me.ai_reason_user && <T style={[s.muted, { fontStyle: "italic" }]}>🤖 “{me.ai_reason_user}”</T>}
        </View>
      )}
      {me?.status === "rejected" && (
        <View style={[s.card, { borderColor: colors.danger }]}>
          <T medium style={{ fontSize: 16, color: colors.danger }}>✗ {t("mjRejected")}</T>
          {!!(me.admin_note || me.ai_reason_user) && (
            <T style={[s.muted, { fontStyle: "italic" }]}>“{me.admin_note || me.ai_reason_user}”</T>
          )}
          <Button title={t("mjTryAgain")} variant="orange" onPress={() => router.push("/mjeshter-apply")} />
        </View>
      )}

      {/* Filters */}
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
        <Pressable onPress={() => setSunday(!sunday)} style={[s.chip, sunday && s.chipOn]}>
          <T medium style={{ color: sunday ? colors.onBlue : colors.text }}>📅 {t("mjFreeSunday")}</T>
        </Pressable>
        <Pressable onPress={() => setSkill(null)} style={[s.chip, !skill && s.chipOn]}>
          <T medium style={{ color: !skill ? colors.onBlue : colors.text }}>{t("all")}</T>
        </Pressable>
        {SKILLS.map((k) => (
          <Pressable key={k} onPress={() => setSkill(skill === k ? null : k)} style={[s.chip, skill === k && s.chipOn]}>
            <T medium style={{ color: skill === k ? colors.onBlue : colors.text }}>
              {SKILL_ICON[k]} {t(`skill_${k}` as TKey)}
            </T>
          </Pressable>
        ))}
      </ScrollView>

      {!!error && <T style={{ color: colors.danger }}>{error}</T>}
      {!loading && list.length === 0 && <T style={[s.muted, { textAlign: "center", marginTop: 20 }]}>{t("mjNone")}</T>}

      {list.map((m, i) => (
        <Animated.View key={m.id} entering={FadeInDown.delay(40 * i)} style={s.card}>
          <View style={s.row}>
            <View style={s.avatar}><T medium style={{ fontSize: 20, color: colors.onBlue }}>{m.name[0]}</T></View>
            <View style={{ flex: 1, gap: 2 }}>
              <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                <T medium style={{ fontSize: 17 }}>{m.name}</T>
                <Ionicons name="checkmark-circle" size={16} color={colors.fixed} />
              </View>
              <T style={s.muted}>📍 {m.neighbourhood ?? "—"}  ·  {LEVEL_ICON[m.level] ?? "🌱"} {t("mjJobsDone", { n: m.jobs_done })}</T>
            </View>
          </View>
          <View style={s.tags}>
            {m.skills.map((k) => (
              <T key={k} style={s.tag}>{SKILL_ICON[k]} {t(`skill_${k}` as TKey)}</T>
            ))}
          </View>
          {m.days.length > 0 && <T style={s.muted}>📅 {m.days.map((d) => t(`day_${d}` as TKey)).join(", ")}</T>}
          {!!m.bio && <T style={{ fontStyle: "italic" }}>“{m.bio}”</T>}
          {citizen && (
            <Button title={t("bkAsk")} variant="orange"
              icon={<Ionicons name="camera" size={18} color="#fff" />}
              onPress={() => router.push({ pathname: "/book", params: { mj: String(m.id), name: m.name, skill: skill ?? (m.skills.length === 1 ? m.skills[0] : "") } })} />
          )}
        </Animated.View>
      ))}
    </ScrollView>
  );
}

const makeStyles = (c: Palette) =>
  StyleSheet.create({
    page: { padding: 16, gap: 12, paddingBottom: 40 },
    hero: { flexDirection: "row", alignItems: "center", gap: 14, padding: 16, borderRadius: 20, backgroundColor: c.blue },
    heroTitle: { color: "#fff", fontSize: 20 },
    heroText: { color: "#fff", opacity: 0.9, fontSize: 14 },
    card: { gap: 8, padding: 14, borderRadius: 18, backgroundColor: c.surface, borderWidth: 1, borderColor: c.line },
    row: { flexDirection: "row", alignItems: "center", gap: 12 },
    avatar: { width: 46, height: 46, borderRadius: 23, alignItems: "center", justifyContent: "center", backgroundColor: c.blue },
    tags: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
    tag: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 999, backgroundColor: c.surface2, fontSize: 13, overflow: "hidden" },
    chip: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: 999, backgroundColor: c.surface2, borderWidth: 1, borderColor: c.line },
    chipOn: { backgroundColor: c.blue, borderColor: c.blue },
    muted: { color: c.muted },
  });
