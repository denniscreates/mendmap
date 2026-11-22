import { router, useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { Alert, Image, Pressable, RefreshControl, ScrollView, StyleSheet, View } from "react-native";
import { StatusPill, T, useTimeAgo } from "../../components/ui";
import { api, photoUrl, type PublicStats, type Report, type TopReport } from "../../lib/api";
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
  const [top, setTop] = useState<TopReport[]>([]);
  const [voted, setVoted] = useState<Set<number>>(new Set());
  const area = user?.role === "citizen" ? user.neighbourhood ?? null : null;
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const homeOn = user?.home_lat != null;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [st, n, open, tp] = await Promise.all([
        api.publicStats(),
        homeOn ? api.nearby() : Promise.resolve([] as Report[]),
        area ? api.reports({ status: "reported" }) : Promise.resolve([] as Report[]),
        api.top10().catch(() => [] as TopReport[]),
      ]);
      setTop(tp);
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
  const speed = [...(stats?.neighbourhoods ?? [])]
    .filter((n) => n.avg_fix_days != null)
    .sort((a, b) => (a.avg_fix_days ?? 0) - (b.avg_fix_days ?? 0));
  const slowest = Math.max(1, ...speed.map((n) => n.avg_fix_days ?? 0));

  const vote = async (r: TopReport) => {
    try {
      await api.confirm(r.id);
      setVoted((v) => new Set(v).add(r.id));
      setTop((cur) => cur.map((x) => (x.id === r.id ? { ...x, confirmations: x.confirmations + 1 } : x)));
    } catch (e) {
      Alert.alert("MendMap", tErr((e as Error).message));
    }
  };

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


      <T medium style={s.section}>🔥 {t("top10Title")}</T>
      <T style={s.muted}>{t("top10Intro")}</T>
      {top.length === 0 ? (
        <T style={s.muted}>{t("top10None")}</T>
      ) : (
        <View style={s.box}>
          {top.map((r, i) => (
            <Pressable key={r.id} style={s.lb} onPress={() => router.push(`/report/${r.id}`)}>
              <T medium style={[s.rank, i < 3 && { color: colors.orange }]}>{i + 1}</T>
              {r.photo_url ? (
                <Image source={{ uri: photoUrl(r.photo_url)! }} style={s.thumb} />
              ) : (
                <View style={[s.thumb, { alignItems: "center", justifyContent: "center" }]}><T>📍</T></View>
              )}
              <View style={{ flex: 1, gap: 3 }}>
                <T medium numberOfLines={2}>{r.title}</T>
                <T style={s.muted} numberOfLines={1}>{r.address || r.neighbourhood || ""}</T>
                <StatusPill status={r.status} />
              </View>
              <Pressable
                onPress={() => void vote(r)}
                disabled={voted.has(r.id) || r.status === "fixed" || user?.role !== "citizen"}
                style={[s.vote, voted.has(r.id) && { backgroundColor: colors.fixed, borderColor: colors.fixed }]}
                hitSlop={6}
              >
                <T style={{ fontSize: 13 }}>👀</T>
                <T medium style={[{ fontSize: 15 }, voted.has(r.id) && { color: "#fff" }]}>{r.confirmations}</T>
              </Pressable>
            </Pressable>
          ))}
        </View>
      )}

      {speed.length > 0 && (
        <>
          <T medium style={s.section}>⏱️ {t("speedTitle")}</T>
          <View style={s.box}>
            {speed.map((n, i) => (
              <View key={n.name} style={s.lb}>
                <T medium style={[s.rank, i < 3 && { color: colors.fixed }]}>{i + 1}</T>
                <View style={{ flex: 1, gap: 5 }}>
                  <View style={{ flexDirection: "row", justifyContent: "space-between", gap: 8 }}>
                    <T medium style={{ flex: 1 }}>{n.name}</T>
                    {!!n.came_back && <T style={[s.muted, { color: colors.orange }]}>{t("cameBackN", { n: n.came_back })}</T>}
                  </View>
                  <View style={[s.meter, { backgroundColor: colors.line }]}>
                    <View style={[s.meterFill, { width: `${Math.max(4, ((n.avg_fix_days ?? 0) / slowest) * 100)}%`, backgroundColor: colors.accent }]} />
                  </View>
                  <T style={s.muted}>{t("speedRow", { d: n.avg_fix_days ?? 0, w: Math.round((n.fixed_in_week ?? 0) * 100) })}</T>
                </View>
              </View>
            ))}
          </View>
        </>
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
    thumb: { width: 46, height: 46, borderRadius: 10, backgroundColor: c.surface2 },
    vote: { alignItems: "center", minWidth: 48, paddingHorizontal: 8, paddingVertical: 6, borderRadius: 12, borderWidth: 1, borderColor: c.line, backgroundColor: c.surface2 },
  });
