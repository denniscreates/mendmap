import Ionicons from "@expo/vector-icons/Ionicons";
import { router, useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { Alert, Linking, Pressable, RefreshControl, ScrollView, StyleSheet, View } from "react-native";
import { Button, T } from "../components/ui";
import { api, type Booking, type Payouts } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useI18n, type TKey } from "../lib/i18n";
import { money, statusTone } from "../lib/money";
import { useStyles, useTheme, type Palette } from "../lib/theme";

/** Paid jobs: the ones I asked for, and (for a mjeshtër) the job requests sent to me. */
export default function Bookings() {
  const { user } = useAuth();
  const { colors } = useTheme();
  const { t, tErr, locale } = useI18n();
  const s = useStyles(makeStyles);
  const isMj = user?.mjeshter_status === "approved";
  const [tab, setTab] = useState<"customer" | "worker">(isMj ? "worker" : "customer");
  const [list, setList] = useState<Booking[] | null>(null);
  const [payouts, setPayouts] = useState<Payouts | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [l, p] = await Promise.all([api.bookings(tab), isMj ? api.payouts().catch(() => null) : Promise.resolve(null)]);
      setList(l);
      setPayouts(p);
      setError("");
    } catch (e) {
      setError(tErr((e as Error).message));
    } finally {
      setLoading(false);
    }
  }, [tab, isMj, tErr]);
  useFocusEffect(useCallback(() => void load(), [load]));

  const setUpPayouts = async () => {
    try {
      const { url } = await api.payoutsOnboard();
      Alert.alert(t("bkPayouts"), t("bkPayoutsBack"), [{ text: "OK", onPress: () => void Linking.openURL(url) }]);
    } catch (e) {
      Alert.alert("MendMap", tErr((e as Error).message));
    }
  };
  const pct = Math.round((payouts?.commission_rate ?? 0.1) * 100);

  return (
    <ScrollView contentContainerStyle={s.page}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={colors.accent} />}>
      {isMj && (
        <View style={s.segment}>
          {(["worker", "customer"] as const).map((k) => (
            <Pressable key={k} onPress={() => setTab(k)} style={[s.seg, tab === k && s.segOn]}>
              <T medium style={{ color: tab === k ? "#fff" : colors.text }}>{k === "worker" ? t("bkJobs") : t("bkMine")}</T>
            </Pressable>
          ))}
        </View>
      )}

      {isMj && tab === "worker" && payouts && payouts.configured && (
        payouts.ready ? (
          <View style={[s.banner, { borderColor: colors.fixed }]}>
            <Ionicons name="checkmark-circle" size={20} color={colors.fixed} />
            <T style={{ flex: 1 }}>{t("bkPayoutsReady")}</T>
          </View>
        ) : (
          <View style={[s.banner, { borderColor: colors.orange, flexDirection: "column", alignItems: "stretch" }]}>
            <T medium style={{ fontSize: 16 }}>💳 {t("bkPayouts")}</T>
            <T style={s.muted}>{t("bkPayoutsBody", { p: pct })}</T>
            <Button title={t("bkPayouts")} variant="orange" onPress={setUpPayouts} />
          </View>
        )
      )}

      {!!error && <T style={{ color: colors.danger }}>{error}</T>}
      {list?.length === 0 && (
        <View style={{ alignItems: "center", gap: 12, padding: 20 }}>
          <T style={{ fontSize: 40 }}>🧰</T>
          <T style={[s.muted, { textAlign: "center" }]}>{tab === "worker" ? t("bkNoneJobs") : t("bkNone")}</T>
          {tab === "customer" && <Button title={t("bkFind")} variant="ghost" onPress={() => router.push("/mjeshtrit")} />}
        </View>
      )}

      {list?.map((b) => (
        <Pressable key={b.id} onPress={() => router.push(`/booking/${b.id}`)}
          style={({ pressed }) => [s.card, pressed && { opacity: 0.7 }]}>
          <View style={[s.stripe, { backgroundColor: statusTone(colors, b.status) }]} />
          <View style={{ flex: 1, gap: 3 }}>
            <T medium numberOfLines={2}>{b.description}</T>
            <T style={s.muted}>{b.as_role === "worker" ? t("bkFrom", { name: b.customer_name }) : t("bkTo", { name: b.worker_name })}</T>
            <T medium style={{ color: statusTone(colors, b.status), fontSize: 13 }}>{t(`bk_${b.status}` as TKey)}</T>
          </View>
          {b.fee_cents != null && <T medium style={{ fontSize: 16 }}>{money(b.fee_cents, b.currency, locale)}</T>}
          <Ionicons name="chevron-forward" size={18} color={colors.muted} />
        </Pressable>
      ))}
    </ScrollView>
  );
}

const makeStyles = (c: Palette) =>
  StyleSheet.create({
    page: { padding: 16, gap: 10, paddingBottom: 40 },
    segment: { flexDirection: "row", padding: 4, borderRadius: 14, backgroundColor: c.surface2, gap: 4 },
    seg: { flex: 1, alignItems: "center", paddingVertical: 9, borderRadius: 11 },
    segOn: { backgroundColor: c.blue },
    banner: { flexDirection: "row", alignItems: "center", gap: 10, padding: 14, borderRadius: 16, borderWidth: 1, backgroundColor: c.surface },
    card: { flexDirection: "row", alignItems: "center", gap: 12, padding: 12, paddingLeft: 0, borderRadius: 16, backgroundColor: c.surface, borderWidth: 1, borderColor: c.line, overflow: "hidden" },
    stripe: { width: 5, alignSelf: "stretch" },
    muted: { color: c.muted, fontSize: 13 },
  });
