import Ionicons from "@expo/vector-icons/Ionicons";
import { useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { Alert, RefreshControl, ScrollView, StyleSheet, View } from "react-native";
import Animated, { FadeInDown } from "react-native-reanimated";
import { Button, T } from "../components/ui";
import { api, type PartnerReward, type Rewards } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useI18n } from "../lib/i18n";
import { useStyles, useTheme, type Palette } from "../lib/theme";

/** Partner rewards: spend fixer badges on offers from local businesses and keep the voucher codes. */
export default function RewardsScreen() {
  const { user } = useAuth();
  const { colors } = useTheme();
  const { t, tErr } = useI18n();
  const s = useStyles(makeStyles);
  const [data, setData] = useState<Rewards | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await api.rewards());
      setError("");
    } catch (e) {
      setError(tErr((e as Error).message));
    } finally {
      setLoading(false);
    }
  }, [tErr]);
  useFocusEffect(useCallback(() => void load(), [load]));

  const get = (r: PartnerReward) =>
    Alert.alert(t("rewardConfirmTitle"), t("rewardConfirmBody", { title: r.title, partner: r.partner, n: r.cost }), [
      { text: t("cancel"), style: "cancel" },
      {
        text: t("rewardGet"),
        onPress: async () => {
          setBusy(r.id);
          try {
            const c = await api.claimReward(r.id);
            Alert.alert(t("rewardGotTitle"), t("rewardGotBody", { code: c.code, partner: c.partner }));
          } catch (e) {
            Alert.alert("MendMap", tErr((e as Error).message));
          } finally {
            setBusy(null);
            load();
          }
        },
      },
    ]);

  const citizen = user?.role === "citizen";

  return (
    <ScrollView
      contentContainerStyle={s.page}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={colors.accent} />}
    >
      {!!error && <T style={{ color: colors.danger }}>{error}</T>}

      {data && (
        <Animated.View entering={FadeInDown} style={s.hero}>
          <T style={{ fontSize: 34 }}>🎁</T>
          <View style={{ flex: 1, gap: 2 }}>
            <T medium style={s.heroTitle}>{t("rewardsBalance", { n: data.balance })}</T>
            <T style={s.heroText}>{t("rewardsIntro")}</T>
          </View>
        </Animated.View>
      )}

      {data && data.rewards.length === 0 && <T style={s.muted}>{t("rewardNone")}</T>}

      {data?.rewards.map((r, i) => {
        const short = r.cost - data.balance;
        return (
          <Animated.View key={r.id} entering={FadeInDown.delay(60 * i)} style={s.card}>
            <View style={s.row}>
              <View style={s.emoji}><T style={{ fontSize: 28 }}>{r.emoji}</T></View>
              <View style={{ flex: 1, gap: 2 }}>
                <T style={s.muted}>{r.partner}</T>
                <T medium style={{ fontSize: 17 }}>{r.title}</T>
                {!!r.details && <T style={[s.muted, { fontSize: 13 }]}>{r.details}</T>}
              </View>
            </View>
            <View style={s.meter}>
              <View style={[s.meterFill, { width: `${Math.min(100, (data.balance / r.cost) * 100)}%` }]} />
            </View>
            <View style={s.row}>
              <View style={{ flex: 1 }}>
                <T medium>🛠️ {t("rewardCost", { n: r.cost })}</T>
                {r.stock != null && <T style={[s.muted, { fontSize: 13 }]}>{t("rewardLeft", { n: r.stock })}</T>}
              </View>
              {citizen && (short > 0
                ? <T style={s.muted}>{t("rewardNeed", { n: short })}</T>
                : <Button title={t("rewardGet")} variant="orange" loading={busy === r.id} onPress={() => get(r)} />)}
            </View>
          </Animated.View>
        );
      })}

      {data && data.claims.length > 0 && (
        <View style={{ gap: 10 }}>
          <T medium style={s.section}>{t("myVouchers")}</T>
          {data.claims.map((c) => (
            <View key={c.id} style={[s.card, s.row, c.used && { opacity: 0.55 }]}>
              <T style={{ fontSize: 26 }}>{c.emoji}</T>
              <View style={{ flex: 1, gap: 2 }}>
                <T medium>{c.title}</T>
                <T style={s.muted}>{c.partner}</T>
              </View>
              <View style={{ alignItems: "flex-end", gap: 2 }}>
                <T medium style={s.code} selectable>{c.code}</T>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
                  <Ionicons name={c.used ? "checkmark-done" : "ticket-outline"} size={14} color={c.used ? colors.muted : colors.fixed} />
                  <T style={[s.muted, { fontSize: 12 }]}>{c.used ? t("voucherUsed") : t("voucherReady")}</T>
                </View>
              </View>
            </View>
          ))}
        </View>
      )}
    </ScrollView>
  );
}

const makeStyles = (c: Palette) =>
  StyleSheet.create({
    page: { padding: 16, gap: 14, paddingBottom: 40 },
    hero: { flexDirection: "row", alignItems: "center", gap: 14, padding: 16, borderRadius: 20, backgroundColor: c.blue },
    heroTitle: { color: "#fff", fontSize: 20 },
    heroText: { color: "#fff", opacity: 0.9, fontSize: 14 },
    card: { gap: 12, padding: 14, borderRadius: 18, backgroundColor: c.surface, borderWidth: 1, borderColor: c.line },
    row: { flexDirection: "row", alignItems: "center", gap: 12 },
    emoji: { width: 52, height: 52, borderRadius: 16, alignItems: "center", justifyContent: "center", backgroundColor: c.surface2 },
    meter: { height: 8, borderRadius: 4, backgroundColor: c.surface2, overflow: "hidden" },
    meterFill: { height: "100%", borderRadius: 4, backgroundColor: c.orange },
    section: { fontSize: 18 },
    muted: { color: c.muted },
    code: { fontSize: 16, letterSpacing: 1.5, color: c.accent },
  });
