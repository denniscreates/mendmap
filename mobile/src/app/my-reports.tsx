import Ionicons from "@expo/vector-icons/Ionicons";
import { router, useFocusEffect } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { FlatList, Image, Pressable, RefreshControl, StyleSheet, View } from "react-native";
import { Button, Segmented, StatusPill, T, useTimeAgo } from "../components/ui";
import { api, photoUrl, type ReportDetail } from "../lib/api";
import { subscribeDrafts, syncDrafts, type Draft } from "../lib/drafts";
import { categoryKey, useI18n } from "../lib/i18n";
import { emojiFor, statusColor, useStyles, useTheme, type Palette, type Status } from "../lib/theme";

const STEPS: Status[] = ["reported", "in_progress", "fixed"];
type Filter = "all" | "open" | "fixed";

/** My reports, opened from Settings: drafts waiting for signal, then each report with its progress. */
export default function MyReportsScreen() {
  const { colors } = useTheme();
  const { t, tErr } = useI18n();
  const timeAgo = useTimeAgo();
  const s = useStyles(makeStyles);
  const [reports, setReports] = useState<ReportDetail[]>([]);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => subscribeDrafts(setDrafts), []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setReports(await api.myReports());
      setError("");
    } catch (e) {
      setError(tErr((e as Error).message));
    } finally {
      setLoading(false);
    }
  }, [tErr]);
  useFocusEffect(useCallback(() => void load(), [load]));

  const shown = reports.filter((r) => (filter === "all" ? true : filter === "fixed" ? r.status === "fixed" : r.status !== "fixed"));
  const fixed = reports.filter((r) => r.status === "fixed").length;

  return (
    <FlatList
      data={shown}
      keyExtractor={(r) => String(r.id)}
      contentContainerStyle={{ padding: 16, gap: 12, flexGrow: 1 }}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={colors.accent} />}
      ListHeaderComponent={
        <View style={{ gap: 12 }}>
          <T style={s.muted}>{t("summary", { n: reports.length, f: fixed })}</T>
          {reports.length > 0 && (
            <Segmented<Filter>
              value={filter}
              onChange={setFilter}
              options={[
                { value: "all", label: t("all") },
                { value: "open", label: t("mapOpen") },
                { value: "fixed", label: t("fixed") },
              ]}
            />
          )}
          {drafts.map((d) => (
            <Pressable key={d.localId} style={[s.card, { borderColor: colors.amber + "66" }]} onPress={() => syncDrafts().then(load)}>
              <Ionicons name="cloud-offline" size={22} color={colors.amber} />
              <View style={{ flex: 1 }}>
                <T medium style={s.title}>{d.categoryName}</T>
                <T style={s.muted}>{t("waitingSignal", { t: timeAgo(d.savedAt) })}</T>
              </View>
              <Ionicons name="refresh" size={18} color={colors.muted} />
            </Pressable>
          ))}
          {!!error && <T style={{ color: colors.danger }}>{error}</T>}
        </View>
      }
      ListEmptyComponent={
        !loading ? (
          <View style={s.empty}>
            <T style={{ fontSize: 48 }}>📍</T>
            <T medium style={s.title}>{t("noReports")}</T>
            <T style={[s.muted, { textAlign: "center" }]}>{t("noReportsBody")}</T>
            <Button title={t("reportProblem")} variant="orange" onPress={() => router.push("/report")} style={{ alignSelf: "stretch", marginTop: 12 }} />
          </View>
        ) : undefined
      }
      renderItem={({ item: r }) => (
        <Pressable style={s.card} onPress={() => router.push(`/report/${r.id}`)}>
          {r.photo_url ? (
            <Image source={{ uri: photoUrl(r.photo_url)! }} style={s.thumb} />
          ) : (
            <View style={[s.thumb, { alignItems: "center", justifyContent: "center" }]}>
              <T style={{ fontSize: 26 }}>{emojiFor(r.category.icon)}</T>
            </View>
          )}
          <View style={{ flex: 1, gap: 6 }}>
            <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
              <T medium style={s.title}>{t(categoryKey(r.category.icon))}</T>
              <T style={s.muted}>{timeAgo(r.updated_at)}</T>
            </View>
            <StatusPill status={r.status} />
            <Progress status={r.status} />
          </View>
        </Pressable>
      )}
    />
  );
}

/** Three-step progress bar: Reported → In progress → Fixed. */
function Progress({ status }: { status: Status }) {
  const { colors } = useTheme();
  const idx = STEPS.indexOf(status);
  return (
    <View style={{ flexDirection: "row", gap: 4 }}>
      {STEPS.map((st, i) => (
        <View key={st} style={{ flex: 1, height: 4, borderRadius: 2, backgroundColor: i <= idx ? statusColor(colors, status) : colors.line }} />
      ))}
    </View>
  );
}

const makeStyles = (c: Palette) =>
  StyleSheet.create({
    muted: { color: c.muted, fontSize: 13 },
    card: {
      flexDirection: "row", gap: 12, alignItems: "center", padding: 12, borderRadius: 16,
      backgroundColor: c.surface, borderWidth: 1, borderColor: c.line,
    },
    thumb: { width: 64, height: 64, borderRadius: 12, backgroundColor: c.surface2 },
    title: { fontSize: 16 },
    empty: { flex: 1, alignItems: "center", justifyContent: "center", gap: 8, padding: 24 },
  });
