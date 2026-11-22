import Ionicons from "@expo/vector-icons/Ionicons";
import { router, useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { Alert, Image, Pressable, RefreshControl, ScrollView, StyleSheet, View } from "react-native";
import Animated, { FadeInDown } from "react-native-reanimated";
import { AreaPicker } from "../../components/area";
import { T } from "../../components/ui";
import { api, photoUrl, type Fixer, type Report, type TopFixer } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { hoursLeft, LEVEL_ICON } from "../../lib/fixer";
import { categoryKey, useI18n, type TKey } from "../../lib/i18n";
import { emojiFor, useStyles, useTheme, type Palette } from "../../lib/theme";


/** Fix & earn: open jobs in your neighbourhood, your jobs, your level and reward, and the top fixers. */
export default function FixScreen() {
  const { user, updateUser } = useAuth();
  const { colors } = useTheme();
  const { t, tErr } = useI18n();
  const s = useStyles(makeStyles);
  const [fixer, setFixer] = useState<Fixer | null>(null);
  const [top, setTop] = useState<TopFixer[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [f, tf] = await Promise.all([api.fixer(), api.topFixers().catch(() => [])]);
      setFixer(f);
      setTop(tf);
      setError("");
    } catch (e) {
      setError(tErr((e as Error).message));
    } finally {
      setLoading(false);
    }
  }, [tErr]);
  useFocusEffect(useCallback(() => void load(), [load]));

  const chooseArea = async (area: string) => {
    try {
      updateUser(await api.setNeighbourhood(area));
      await load();
    } catch (e) {
      Alert.alert("MendMap", tErr((e as Error).message));
    }
  };

  const take = (r: Report) =>
    Alert.alert(t("fixItTitle"), t("fixItBody"), [
      { text: t("cancel"), style: "cancel" },
      {
        text: t("fixIt"),
        onPress: async () => {
          setBusy(r.id);
          try {
            await api.claim(r.id);
            router.push(`/report/${r.id}`);
          } catch (e) {
            Alert.alert("MendMap", tErr((e as Error).message));
            load();
          } finally {
            setBusy(null);
          }
        },
      },
    ]);

  const full = !!fixer && fixer.active.length >= fixer.max_active;
  const goal = fixer?.next_reward ?? null;
  const ready = !!goal && fixer!.balance >= goal.cost;

  return (
    <ScrollView
      contentContainerStyle={s.page}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={colors.accent} />}
    >
      {!!error && <T style={{ color: colors.danger }}>{error}</T>}

      {/* Level and reward */}
      {fixer && (
        <Animated.View entering={FadeInDown} style={s.hero}>
          <View style={s.heroRow}>
            <View style={s.levelBadge}>
              <T style={{ fontSize: 30 }}>{LEVEL_ICON[fixer.level] ?? "🛠️"}</T>
            </View>
            <View style={{ flex: 1, gap: 2 }}>
              <T medium style={s.heroTitle}>{t(`level_${fixer.level}` as TKey)}</T>
              <T style={s.heroText}>
                {fixer.next_level_at != null
                  ? t("nextLevel", { n: fixer.next_level_at - fixer.verified })
                  : t("topLevel")}
              </T>
            </View>
            <View style={{ alignItems: "center" }}>
              <T medium style={s.heroBig}>{fixer.verified}</T>
              <T style={s.heroText}>{t("badgesShort")}</T>
            </View>
          </View>
          {goal && (
            <>
              <View style={s.meter}>
                <View style={[s.meterFill, { width: `${Math.min(100, (fixer.balance / goal.cost) * 100)}%` }]} />
              </View>
              <T style={s.heroText}>
                {goal.emoji}{" "}
                {ready
                  ? t("rewardReady", { title: goal.title, partner: goal.partner })
                  : t("nextRewardProgress", { n: fixer.balance, cost: goal.cost, title: goal.title, partner: goal.partner })}
              </T>
            </>
          )}
          {fixer.pending > 0 && <T style={s.heroText}>⏳ {t("fixerPending", { n: fixer.pending })}</T>}
          <Pressable onPress={() => router.push("/rewards")} style={({ pressed }) => [s.rewardsBtn, pressed && { opacity: 0.7 }]}>
            <T medium style={{ color: colors.blue }}>🎁 {t("seeRewards")}</T>
            <Ionicons name="chevron-forward" size={16} color={colors.blue} />
          </Pressable>
        </Animated.View>
      )}

      {/* No area yet: optional, it only puts jobs near home first and turns on job alerts. */}
      {user && !user.neighbourhood && (
        <View style={s.card}>
          <T medium style={{ fontSize: 16 }}>📍 {t("setAreaTitle")}</T>
          <T style={s.muted}>{t("setAreaBody")}</T>
          <AreaPicker value={null} onChange={chooseArea} />
        </View>
      )}

      {/* My jobs */}
      {fixer && fixer.active.length > 0 && (
        <View style={{ gap: 10 }}>
          <T medium style={s.section}>{t("yourJobs", { n: fixer.active.length, max: fixer.max_active })}</T>
          {fixer.active.map((r) => {
            const h = hoursLeft(r.claim_deadline);
            return (
              <Pressable key={r.id} style={[s.job, s.mine]} onPress={() => router.push(`/report/${r.id}`)}>
                <Thumb r={r} />
                <View style={{ flex: 1, gap: 3 }}>
                  <T medium>{emojiFor(r.category.icon)} {t(categoryKey(r.category.icon))}</T>
                  {h != null && (
                    <T style={{ color: h <= 6 ? colors.danger : colors.orange, fontSize: 13 }}>⏱ {t("finishWithin", { h })}</T>
                  )}
                  <T medium style={{ color: colors.accent, fontSize: 14 }}>{t("sendAfterShort")} ›</T>
                </View>
              </Pressable>
            );
          })}
        </View>
      )}

      {/* Every open job the AI calls safe, in any neighbourhood (own area first) */}
      {fixer && (
        <View style={{ gap: 10 }}>
          <T medium style={s.section}>{t("openFixJobs", { n: fixer.available.length })}</T>
          <T style={s.muted}>{t("openJobsHint")}</T>
          {full && <T style={s.muted}>{t("finishFirst", { max: fixer.max_active })}</T>}
          {fixer.available.length === 0 ? (
            <View style={s.card}>
              <T style={{ fontSize: 28, textAlign: "center" }}>✨</T>
              <T style={[s.muted, { textAlign: "center" }]}>{t("noJobs")}</T>
            </View>
          ) : (
            fixer.available.map((r, i) => (
              <Animated.View key={r.id} entering={FadeInDown.delay(i * 60)}>
                <Pressable style={s.job} onPress={() => router.push(`/report/${r.id}`)}>
                  <Thumb r={r} />
                  <View style={{ flex: 1, gap: 3 }}>
                    <T medium>{emojiFor(r.category.icon)} {t(categoryKey(r.category.icon))}</T>
                    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
                      {!!r.neighbourhood && (
                        <T style={[s.tag, r.neighbourhood === user?.neighbourhood && s.tagHome]}>
                          📍 {r.neighbourhood === user?.neighbourhood ? t("yourArea") : r.neighbourhood}
                        </T>
                      )}
                      {r.ai_neighbour_safe && <T style={[s.tag, s.tagSafe]}>✨ {t("aiSafeShort")}</T>}
                    </View>
                    <T style={s.muted} numberOfLines={2}>{r.ai_safety_reason || r.description || t("noDescription")}</T>
                    {r.confirmations > 0 && <T style={[s.muted, { fontSize: 12 }]}>{t("othersSeeIt", { n: r.confirmations })}</T>}
                  </View>
                  <Pressable
                    onPress={() => take(r)}
                    disabled={full || busy === r.id}
                    style={[s.takeBtn, (full || busy === r.id) && { opacity: 0.4 }]}
                    accessibilityRole="button"
                    accessibilityLabel={t("fixIt")}
                  >
                    <Ionicons name="hammer" size={16} color="#fff" />
                    <T medium style={{ color: "#fff", fontSize: 14 }}>{t("take")}</T>
                  </Pressable>
                </Pressable>
              </Animated.View>
            ))
          )}
        </View>
      )}

      {/* Mjeshtrit: skilled volunteers */}
      <Pressable onPress={() => router.push("/mjeshtrit")} style={({ pressed }) => [s.card, s.mjCard, pressed && { opacity: 0.7 }]}>
        <T style={{ fontSize: 30 }}>🧰</T>
        <View style={{ flex: 1, gap: 2 }}>
          <T medium style={{ fontSize: 16 }}>{t("mjTitle")}</T>
          <T style={s.muted}>
            {user?.mjeshter_status === "approved" ? t("mjCardVerified") : t("mjCardBody")}
          </T>
        </View>
        <Ionicons name="chevron-forward" size={18} color={colors.muted} />
      </Pressable>

      {/* How it works */}
      <View style={s.card}>
        <T medium style={{ fontSize: 16 }}>{t("howItWorks")}</T>
        {(["how1", "how2", "how3", "how4"] as const).map((k, i) => (
          <View key={k} style={s.howRow}>
            <View style={s.howNum}><T medium style={{ color: colors.onBlue, fontSize: 13 }}>{i + 1}</T></View>
            <T style={{ flex: 1 }}>{t(k, { h: fixer?.claim_hours ?? 48 })}</T>
          </View>
        ))}
      </View>

      {/* Top fixers */}
      {top.length > 0 && (
        <View style={s.card}>
          <T medium style={{ fontSize: 16 }}>{t("topFixers")}</T>
          {top.map((f, i) => (
            <View key={`${f.name}-${i}`} style={s.topRow}>
              <T medium style={{ width: 24, color: i < 3 ? colors.orange : colors.muted }}>{i + 1}</T>
              <T style={{ fontSize: 18 }}>{LEVEL_ICON[f.level] ?? "🛠️"}</T>
              <View style={{ flex: 1 }}>
                <T medium>{f.name}</T>
                {!!f.neighbourhood && <T style={[s.muted, { fontSize: 12 }]}>{f.neighbourhood}</T>}
              </View>
              <T medium style={{ color: colors.orange }}>{t("fixerBadges", { n: f.badges })}</T>
            </View>
          ))}
        </View>
      )}
    </ScrollView>
  );
}

function Thumb({ r }: { r: Report }) {
  const s = useStyles(makeStyles);
  return r.photo_url ? (
    <Image source={{ uri: photoUrl(r.photo_url)! }} style={s.thumb} />
  ) : (
    <View style={[s.thumb, { alignItems: "center", justifyContent: "center" }]}>
      <T style={{ fontSize: 26 }}>{emojiFor(r.category.icon)}</T>
    </View>
  );
}

const makeStyles = (c: Palette) =>
  StyleSheet.create({
    page: { padding: 16, gap: 16, paddingBottom: 40 },
    hero: { padding: 16, gap: 10, borderRadius: 20, backgroundColor: c.blue },
    heroRow: { flexDirection: "row", alignItems: "center", gap: 12 },
    levelBadge: { width: 56, height: 56, borderRadius: 28, alignItems: "center", justifyContent: "center", backgroundColor: "#ffffff26" },
    heroTitle: { color: "#fff", fontSize: 20 },
    heroText: { color: "#fff", opacity: 0.9, fontSize: 14 },
    heroBig: { color: "#fff", fontSize: 30 },
    mjCard: { flexDirection: "row", alignItems: "center", gap: 12 },
    rewardsBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 4, paddingVertical: 10,
      borderRadius: 12, backgroundColor: "#fff" },
    meter: { height: 10, borderRadius: 5, backgroundColor: "#ffffff33", overflow: "hidden" },
    meterFill: { height: "100%", borderRadius: 5, backgroundColor: c.orange },
    card: { padding: 14, gap: 10, borderRadius: 16, backgroundColor: c.surface, borderWidth: 1, borderColor: c.line },
    section: { fontSize: 17 },
    muted: { color: c.muted, fontSize: 14 },
    job: {
      flexDirection: "row", alignItems: "center", gap: 12, padding: 10, borderRadius: 16,
      backgroundColor: c.surface, borderWidth: 1, borderColor: c.line,
    },
    mine: { borderColor: c.orange, borderWidth: 1.5 },
    thumb: { width: 64, height: 64, borderRadius: 12, backgroundColor: c.surface2 },
    takeBtn: {
      flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 12, paddingVertical: 9,
      borderRadius: 999, backgroundColor: c.orange,
    },
    tag: { fontSize: 12, paddingHorizontal: 8, paddingVertical: 2, borderRadius: 999, backgroundColor: c.surface2, overflow: "hidden" },
    tagHome: { backgroundColor: c.orange + "26", color: c.orange },
    tagSafe: { backgroundColor: c.fixed + "26", color: c.fixed },
    howRow: { flexDirection: "row", alignItems: "flex-start", gap: 10 },
    howNum: { width: 22, height: 22, borderRadius: 11, alignItems: "center", justifyContent: "center", backgroundColor: c.blue, marginTop: 1 },
    topRow: { flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 4 },
  });
