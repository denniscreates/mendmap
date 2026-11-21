import { router, useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { Pressable, RefreshControl, ScrollView, StyleSheet, View } from "react-native";
import { StatusPill, T, useTimeAgo } from "../../components/ui";
import { api, type PublicStats, type Report } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { categoryKey, useI18n } from "../../lib/i18n";
import { emojiFor, useStyles, useTheme, type Palette } from "../../lib/theme";

/** Public transparency in the app: city stats, neighbourhood leaderboard, before/after and near-you. */
export default function City() {
  const { user } = useAuth();
  const { colors } = useTheme();
  const { t, tErr } = useI18n();
  const timeAgo = useTimeAgo();
  const s = useStyles(makeStyles);
  const [stats, setStats] = useState<PublicStats | null>(null);
  const [nearby, setNearby] = useState<Report[]>([]);
  const [fixable, setFixable] = useState<Report[]>([]);
  const area = user?.role === "citizen" ? user.neighbourhood ?? null : null;
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const homeOn = user?.home_lat != null;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [st, n, open] = await Promise.all([
        api.publicStats(),
        homeOn ? api.nearby() : Promise.resolve([] as Report[]),
        area ? api.reports({ status: "reported" }) : Promise.resolve([] as Report[]),
      ]);
      setFixable(open.filter((r) => r.neighbourhood === area && r.neighbour_fixable && !r.claimed_by));
      setStats(st);
      setNearby(n);
      setError("");
    } catch (e) {
      setError(tErr((e as Error).message));
    } finally {
      setLoading(false);
    }
  }, [homeOn, area, tErr]);
  useFocusEffect(useCallback(() => void load(), [load]));

  const max = Math.max(1, ...(stats?.neighbourhoods.map((n) => n.total) ?? [1]));

  return (
    <ScrollView
      contentContainerStyle={{ padding: 16, gap: 12, paddingBottom: 40 }}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={colors.accent} />}
    >
      <T medium style={{ fontSize: 22 }}>{t("cityTitle")}</T>
      {!!error && <T style={{ color: colors.danger }}>{error}</T>}

      {stats && (
        <View style={s.cards}>
          <Stat label={t("statFixRate")} value={`${Math.round(stats.fix_rate * 100)}%`} color={colors.fixed} />
          <Stat label={t("fixed")} value={String(stats.fixed)} color={colors.fixed} />
          <Stat label={t("in_progress")} value={String(stats.in_progress)} color={colors.in_progress} />
          <Stat label={t("statAvgFix")} value={stats.avg_days_to_fix != null ? t("daysN", { n: stats.avg_days_to_fix }) : "—"} />
        </View>
      )}

      {!!area && (
        <>
          <T medium style={s.section}>🛠️ {t("canFixHere", { area })}</T>
          {fixable.length === 0 ? (
            <T style={s.muted}>{t("canFixEmpty", { area })}</T>
          ) : (
            fixable.map((r) => (
              <Pressable key={r.id} style={[s.row, { borderColor: colors.orange + "88" }]} onPress={() => router.push(`/report/${r.id}`)}>
                <T style={{ fontSize: 22 }}>{emojiFor(r.category.icon)}</T>
                <View style={{ flex: 1, gap: 4 }}>
                  <T medium>{t(categoryKey(r.category.icon))}</T>
                  <T style={s.muted} numberOfLines={1}>{r.description || t("noDescription")}</T>
                </View>
                <T medium style={{ color: colors.orange }}>{t("fixIt")}</T>
              </Pressable>
            ))
          )}
        </>
      )}

      {user?.role === "citizen" && <T medium style={s.section}>{t("nearYou")}</T>}
      {user?.role !== "citizen" ? null : !homeOn ? (
        <T style={s.muted}>{t("nearYouOff")}</T>
      ) : nearby.length === 0 ? (
        <T style={s.muted}>{t("nearYouEmpty")}</T>
      ) : (
        nearby.slice(0, 8).map((r) => (
          <Pressable key={r.id} style={s.row} onPress={() => router.push(`/report/${r.id}`)}>
            <T style={{ fontSize: 22 }}>{emojiFor(r.category.icon)}</T>
            <View style={{ flex: 1, gap: 4 }}>
              <T medium>{t(categoryKey(r.category.icon))}</T>
              <T style={s.muted}>
                {r.distance_m != null ? `${t("mAway", { n: Math.round(r.distance_m) })} · ` : ""}
                {timeAgo(r.updated_at)}
              </T>
            </View>
            <StatusPill status={r.status} />
          </Pressable>
        ))
      )}

      {stats && stats.neighbourhoods.length > 0 && (
        <>
          <T medium style={s.section}>{t("leaderboard")}</T>
          <View style={s.box}>
            {stats.neighbourhoods.map((n, i) => (
              <View key={n.name} style={s.lb}>
                <T medium style={[s.rank, i < 3 && { color: colors.orange }]}>{i + 1}</T>
                <View style={{ flex: 1, gap: 5 }}>
                  <T medium>{n.name}</T>
                  <View style={s.meter}>
                    <View style={[s.meterFill, { width: `${(n.total / max) * 100}%`, backgroundColor: colors.line }]} />
                    <View style={[s.meterFill, { position: "absolute", width: `${(n.fixed / max) * 100}%`, backgroundColor: colors.fixed }]} />
                  </View>
                  <T style={s.muted}>{t("lbRow", { n: n.total, p: Math.round(n.fix_rate * 100) })}</T>
                </View>
              </View>
            ))}
          </View>
        </>
      )}

    </ScrollView>
  );
}

function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  const s = useStyles(makeStyles);
  return (
    <View style={s.stat}>
      <T style={s.muted}>{label}</T>
      <T medium style={[{ fontSize: 24 }, color ? { color } : null]}>{value}</T>
    </View>
  );
}

const makeStyles = (c: Palette) =>
  StyleSheet.create({
    cards: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
    stat: { width: "47%", flexGrow: 1, padding: 14, borderRadius: 16, backgroundColor: c.surface, borderWidth: 1, borderColor: c.line, gap: 4 },
    section: { fontSize: 17, marginTop: 10 },
    muted: { color: c.muted, fontSize: 13 },
    row: { flexDirection: "row", alignItems: "center", gap: 12, padding: 12, borderRadius: 14, backgroundColor: c.surface, borderWidth: 1, borderColor: c.line },
    box: { padding: 12, borderRadius: 16, backgroundColor: c.surface, borderWidth: 1, borderColor: c.line, gap: 14 },
    lb: { flexDirection: "row", gap: 12, alignItems: "center" },
    rank: { width: 22, fontSize: 16, color: c.muted, textAlign: "center" },
    meter: { height: 6, borderRadius: 3, overflow: "hidden" },
    meterFill: { height: 6, borderRadius: 3 },
  });
