import Ionicons from "@expo/vector-icons/Ionicons";
import { router, useFocusEffect, useLocalSearchParams } from "expo-router";
import { useCallback, useState } from "react";
import { ActivityIndicator, Alert, Image, KeyboardAvoidingView, Platform, Pressable, RefreshControl, ScrollView, StyleSheet, View } from "react-native";
import { Button, Input, T } from "../../components/ui";
import { api, authHeaders, bookingPhotoUrl, type Booking } from "../../lib/api";
import { useI18n, type TKey } from "../../lib/i18n";
import { money, statusTone } from "../../lib/money";
import { payWithStripe } from "../../lib/pay";
import { useStyles, useTheme, type Palette } from "../../lib/theme";

/**
 * One booking. The mjeshtër sees the photo and names a price; the resident pays it with Apple Pay or card.
 * MendMap's commission is part of the price: the mjeshtër sees what they get, the resident sees the fee is included.
 */
export default function BookingScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { colors } = useTheme();
  const { t, tErr, locale } = useI18n();
  const s = useStyles(makeStyles);
  const [b, setB] = useState<Booking | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [fee, setFee] = useState("");
  const [note, setNote] = useState("");

  const show = useCallback((x: Booking) => {
    setB(x);
    if (x.fee_cents != null) setFee(String(x.fee_cents / 100));
    setNote(x.quote_note ?? "");
  }, []);

  const load = useCallback(async () => {
    try {
      show(await api.booking(Number(id)));
      setError("");
    } catch (e) {
      setError(tErr((e as Error).message));
    }
  }, [id, show, tErr]);
  useFocusEffect(useCallback(() => void load(), [load]));

  const run = async (what: string, job: () => Promise<Booking>, done?: string) => {
    setBusy(what);
    try {
      show(await job());
      if (done) Alert.alert("MendMap", done);
    } catch (e) {
      Alert.alert("MendMap", tErr((e as Error).message));
    } finally {
      setBusy(null);
    }
  };
  const ask = (title: string, body: string, ok: string, job: () => void) =>
    Alert.alert(title, body, [{ text: t("cancel"), style: "cancel" }, { text: ok, onPress: job }]);

  if (!b)
    return (
      <View style={s.center}>
        {error ? <T style={{ color: colors.danger }}>{error}</T> : <ActivityIndicator color={colors.accent} />}
      </View>
    );

  const worker = b.as_role === "worker";
  const open = b.status === "requested" || b.status === "quoted";
  const pct = Math.round(b.commission_rate * 100);
  const total = money(b.fee_cents, b.currency, locale);
  const feeNum = Number(fee.replace(",", "."));
  const feeOk = Number.isFinite(feeNum) && feeNum >= 5 && feeNum <= 5000;
  const previewCut = Math.round(feeNum * 100 * b.commission_rate);

  const pay = async () => {
    setBusy("pay");
    try {
      const p = await api.payBooking(b.id);
      if (p.mode === "demo") {
        setBusy(null);
        return ask(t("bkDemo"), t("bkDemoAsk", { amount: total }), t("bkPay", { amount: total }),
          () => void run("pay", () => api.confirmBookingPayment(b.id)));
      }
      if (!(await payWithStripe(p))) return; // closed the sheet
      show(await api.confirmBookingPayment(b.id));
    } catch (e) {
      Alert.alert("MendMap", tErr((e as Error).message));
    } finally {
      setBusy(null);
    }
  };

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined} keyboardVerticalOffset={90}>
      <ScrollView contentContainerStyle={s.page} keyboardShouldPersistTaps="handled"
        refreshControl={<RefreshControl refreshing={false} onRefresh={load} tintColor={colors.accent} />}>
        {/* Status */}
        <View style={[s.status, { backgroundColor: statusTone(colors, b.status) }]}>
          <T medium style={{ color: "#fff", fontSize: 16 }}>{t(`bk_${b.status}` as TKey)}</T>
          <T style={{ color: "#fff", opacity: 0.9 }}>
            {worker ? t("bkFrom", { name: b.customer_name }) : t("bkTo", { name: b.worker_name })}
          </T>
        </View>

        {b.has_photo && (
          <Image source={{ uri: bookingPhotoUrl(b.id), headers: authHeaders() }} style={s.photo} resizeMode="cover" />
        )}
        <View style={s.card}>
          <T style={{ fontSize: 16, lineHeight: 22 }}>{b.description}</T>
          {!!b.address && <T style={s.muted}>📍 {b.address}</T>}
          {b.report_id != null && (
            <Pressable onPress={() => router.push(`/report/${b.report_id}`)}>
              <T style={{ color: colors.accent }}>#{b.report_id} ›</T>
            </Pressable>
          )}
        </View>

        {/* Price */}
        {b.fee_cents != null && (
          <View style={[s.card, { borderColor: b.status === "quoted" ? colors.orange : colors.line }]}>
            <View style={s.line}><T>{t("bkFee")}</T><T medium style={{ fontSize: 22 }}>{total}</T></View>
            {worker ? (
              <>
                <View style={s.line}><T style={s.muted}>{t("bkCommission", { p: pct })}</T><T style={s.muted}>−{money(b.commission_cents, b.currency, locale)}</T></View>
                <View style={[s.line, s.top]}><T medium>{t("bkYouGet")}</T><T medium style={{ color: colors.fixed, fontSize: 18 }}>{money(b.worker_gets_cents, b.currency, locale)}</T></View>
              </>
            ) : (
              <T style={s.muted}>{t("bkCommission", { p: pct })} · {t("bkCommissionWhy")}</T>
            )}
            {!!b.quote_note && <T style={{ fontStyle: "italic" }}>“{b.quote_note}”</T>}
          </View>
        )}

        {/* Resident */}
        {!worker && b.status === "requested" && <T style={[s.muted, { textAlign: "center" }]}>{t("bkWaiting", { name: b.worker_name })}</T>}
        {!worker && b.status === "quoted" && (
          <>
            <Button title={t("bkPay", { amount: total })} variant="orange" onPress={pay} loading={busy === "pay"}
              icon={<Ionicons name="card" size={20} color="#fff" />} />
            <View style={s.payHint}>
              <Ionicons name="logo-apple" size={16} color={colors.muted} />
              <T style={s.muted}>{t("bkPayHint")}</T>
              <Ionicons name="lock-closed" size={13} color={colors.muted} />
              <T style={s.muted}>Stripe</T>
            </View>
          </>
        )}
        {!worker && b.status === "paid" && <T style={[s.muted, { textAlign: "center" }]}>{t("bkPaid", { name: b.worker_name })}</T>}
        {b.status === "declined" && (
          <T style={[s.muted, { textAlign: "center" }]}>{t("bkDeclinedBy", { name: b.worker_name })}{b.decline_note ? ` “${b.decline_note}”` : ""}</T>
        )}

        {/* Mjeshtër: name the price */}
        {worker && open && (
          <View style={s.card}>
            <T medium style={{ fontSize: 16 }}>{t("bkQuoteTitle")}</T>
            <T style={s.muted}>{t("bkQuoteHint")}</T>
            <View style={s.feeRow}>
              <T medium style={{ fontSize: 24 }}>€</T>
              <Input value={fee} onChangeText={setFee} keyboardType="decimal-pad" placeholder="40" style={s.feeInput} maxLength={7} />
            </View>
            {feeOk && (
              <T style={s.muted}>
                {t("bkCommission", { p: pct })}: {money(previewCut, b.currency, locale)} · {t("bkYouGet")}: {money(Math.round(feeNum * 100) - previewCut, b.currency, locale)}
              </T>
            )}
            <Input value={note} onChangeText={setNote} placeholder={t("bkQuoteNote")} maxLength={500} />
            <Button title={b.status === "quoted" ? t("bkChangeQuote") : t("bkSendQuote")} disabled={!feeOk} loading={busy === "quote"}
              onPress={() => run("quote", () => api.quoteBooking(b.id, Math.round(feeNum * 100) / 100, note.trim()))} />
          </View>
        )}
        {worker && b.status === "paid" && <T style={[s.muted, { textAlign: "center" }]}>{t("bkPaidWorker")}</T>}

        {b.status === "paid" && (
          <Button title={t("bkDone")} loading={busy === "done"} icon={<Ionicons name="checkmark-done" size={18} color="#fff" />}
            onPress={() => ask(t("bkDone"), t("bkDoneAsk"), t("bkDone"), () => void run("done", () => api.bookingDone(b.id), t("bkThanks")))} />
        )}
        {worker && open && (
          <Button title={t("bkDecline")} variant="ghost" loading={busy === "decline"}
            onPress={() => ask(t("bkDecline"), t("bkDeclineAsk"), t("bkDecline"), () => void run("decline", () => api.declineBooking(b.id)))} />
        )}
        {!worker && open && (
          <Button title={t("bkCancel")} variant="ghost" loading={busy === "cancel"}
            onPress={() => ask(t("bkCancel"), t("bkCancelAsk"), t("bkCancel"), () => void run("cancel", () => api.cancelBooking(b.id)))} />
        )}
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const makeStyles = (c: Palette) =>
  StyleSheet.create({
    center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 30 },
    page: { padding: 16, gap: 12, paddingBottom: 60 },
    status: { padding: 14, borderRadius: 16, gap: 2 },
    photo: { width: "100%", aspectRatio: 4 / 3, borderRadius: 18, backgroundColor: c.surface2 },
    card: { gap: 10, padding: 14, borderRadius: 16, backgroundColor: c.surface, borderWidth: 1, borderColor: c.line },
    line: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", gap: 10 },
    top: { borderTopWidth: 1, borderTopColor: c.line, paddingTop: 10 },
    muted: { color: c.muted, fontSize: 13 },
    payHint: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6 },
    feeRow: { flexDirection: "row", alignItems: "center", gap: 8 },
    feeInput: { flex: 1, fontSize: 24 },
  });
