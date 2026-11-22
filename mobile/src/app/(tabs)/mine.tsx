import Ionicons from "@expo/vector-icons/Ionicons";
import { router, useFocusEffect } from "expo-router";
import * as Location from "expo-location";
import { useCallback, useEffect, useState } from "react";
import Constants from "expo-constants";
import { Alert, Pressable, RefreshControl, ScrollView, StyleSheet, View } from "react-native";
import { AreaPicker } from "../../components/area";
import { LanguagePicker } from "../../components/LanguagePicker";
import { Button, Segmented, T } from "../../components/ui";
import { api, type Badge, type CrewStats, type Fixer, type ReportDetail } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { subscribeDrafts, type Draft } from "../../lib/drafts";
import { LANG_NAME, useI18n, type Lang, type TKey } from "../../lib/i18n";
import { useStyles, useTheme, type Palette, type ThemeMode } from "../../lib/theme";
import { showWelcome } from "../../lib/welcome";

const BADGE_ICON: Record<string, string> = {
  first_report: "📸", reporter_5: "🖐️", mended: "🔧", confirmer: "🤝", accessibility: "♿", local_hero: "🏅",
};

export default function SettingsScreen() {
  const { user } = useAuth();
  // Crew don't report problems, so they get a work profile instead of reports and badges.
  return user?.role === "crew" ? <CrewProfile /> : <CitizenSettings />;
}

/** Appearance and language switches, shared by both profiles. */
function Settings() {
  const { mode, setMode } = useTheme();
  const { t, tErr, lang, langs, setLang, mainLang, setMainLang } = useI18n();
  const { user, updateUser } = useAuth();
  const s = useStyles(makeStyles);
  // The main language is kept on the account, so it follows the person to a new phone.
  const changeMain = async (l: Lang) => {
    const before = mainLang;
    setMainLang(l);
    if (!user) return;
    try {
      updateUser(await api.setLanguage(l));
    } catch (e) {
      setMainLang(before);
      Alert.alert("MendMap", tErr((e as Error).message));
    }
  };
  return (
    <>
      <T style={s.label}>{t("appearance")}</T>
      <Segmented<ThemeMode>
        value={mode}
        onChange={setMode}
        options={[
          { value: "system", label: t("system") },
          { value: "light", label: t("light") },
          { value: "dark", label: t("dark") },
        ]}
      />
      {/* English, the language of the country you're in (e.g. Italiano in Italy) and your main language. */}
      {langs.length > 1 && (
        <>
          <T style={s.label}>{t("language")}</T>
          <Segmented<Lang>
            value={lang}
            onChange={setLang}
            options={langs.map((l) => ({ value: l, label: LANG_NAME[l] ?? l.toUpperCase() }))}
          />
        </>
      )}
      <T style={s.label}>{t("mainLang")}</T>
      <LanguagePicker value={mainLang} onChange={(l) => void changeMain(l)} />
      <T style={[s.muted, { fontSize: 12 }]}>{t("mainLangHint")}</T>
    </>
  );
}

function CrewProfile() {
  const { user, signOut } = useAuth();
  const { colors } = useTheme();
  const { t, tErr } = useI18n();
  const s = useStyles(makeStyles);
  const [stats, setStats] = useState<CrewStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setStats(await api.crewStats());
      setError("");
    } catch (e) {
      setError(tErr((e as Error).message));
    } finally {
      setLoading(false);
    }
  }, [tErr]);
  useFocusEffect(useCallback(() => void load(), [load]));

  const cells: [string, string, string?][] = stats
    ? [
        [t("crewOpen"), String(stats.open_jobs), colors.in_progress],
        [t("crewToday"), String(stats.fixed_today), colors.fixed],
        [t("crewWeek"), String(stats.fixed_week)],
        [t("crewTotal"), String(stats.fixed_total)],
        [t("crewAvg"), stats.avg_days_to_fix != null ? t("daysN", { n: stats.avg_days_to_fix }) : "—"],
      ]
    : [];

  return (
    <ScrollView
      contentContainerStyle={{ padding: 16, gap: 12 }}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={colors.accent} />}
    >
      <View style={s.profile}>
        <View style={s.profileTop}>
          <View style={{ flex: 1 }}>
            <T medium style={s.hello}>{t("hi", { name: user?.name?.split(" ")[0] ?? "" })}</T>
            <T style={s.muted}>🦺 {t("crewRole")}</T>
          </View>
          <Pressable onPress={signOut} hitSlop={10} accessibilityLabel={t("signOut")}>
            <Ionicons name="log-out-outline" size={24} color={colors.muted} />
          </Pressable>
        </View>
        <Settings />
      </View>

      {!!error && <T style={{ color: colors.danger }}>{error}</T>}
      <View style={s.statGrid}>
        {cells.map(([label, value, color]) => (
          <View key={label} style={s.stat}>
            <T style={s.muted}>{label}</T>
            <T medium style={[{ fontSize: 24 }, color ? { color } : null]}>{value}</T>
          </View>
        ))}
      </View>
      <Button title={t("openJobs")} onPress={() => router.push("/jobs")} icon={<Ionicons name="construct" size={18} color="#fff" />} />
      <T style={[s.muted, { textAlign: "center" }]}>{t("crewNoReports")}</T>
    </ScrollView>
  );
}

/** Settings for residents: account, a button to My reports, look and language, area, alerts, badges, sign out. */
function CitizenSettings() {
  const { user, signOut, updateUser } = useAuth();
  const { colors } = useTheme();
  const { t, tErr } = useI18n();
  const s = useStyles(makeStyles);
  const [reports, setReports] = useState<ReportDetail[]>([]);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [badges, setBadges] = useState<Badge[]>([]);
  const [homeBusy, setHomeBusy] = useState(false);
  const [fixer, setFixer] = useState<Fixer | null>(null);
  const [editArea, setEditArea] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => subscribeDrafts(setDrafts), []);

  const load = useCallback(async () => {
    setLoading(true);
    await Promise.all([
      api.myReports().then(setReports).catch(() => {}),
      api.badges().then(setBadges).catch(() => {}),
      api.fixer().then(setFixer).catch(() => {}),
    ]);
    setLoading(false);
  }, []);
  useFocusEffect(useCallback(() => void load(), [load]));

  const open = reports.filter((r) => r.status !== "fixed").length;
  const homeOn = user?.home_lat != null && user?.home_lng != null;
  const earned = badges.filter((b) => b.earned).length;

  const chooseArea = async (area: string) => {
    try {
      updateUser(await api.setNeighbourhood(area));
      setEditArea(false);
      api.fixer().then(setFixer).catch(() => {});
    } catch (e) {
      Alert.alert("MendMap", tErr((e as Error).message));
    }
  };

  const setHome = async (on: boolean) => {
    setHomeBusy(true);
    try {
      if (on) {
        const { status } = await Location.requestForegroundPermissionsAsync();
        if (status !== "granted") return Alert.alert(t("alertsTitle"), t("locPermOff"));
        const pos = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
        updateUser(await api.setHome({ latitude: pos.coords.latitude, longitude: pos.coords.longitude }));
        Alert.alert(t("alertsTitle"), t("alertsSaved"));
      } else {
        updateUser(await api.setHome(null));
      }
    } catch (e) {
      Alert.alert("MendMap", tErr((e as Error).message));
    } finally {
      setHomeBusy(false);
    }
  };

  const askSignOut = () =>
    Alert.alert(t("signOut"), t("signOutAsk"), [
      { text: t("cancel"), style: "cancel" },
      { text: t("signOut"), style: "destructive", onPress: signOut },
    ]);

  return (
    <ScrollView
      contentContainerStyle={{ padding: 16, gap: 16, paddingBottom: 40 }}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={colors.accent} />}
    >
      {/* Account */}
      <View style={[s.profile, s.profileTop]}>
        <View style={s.avatar}>
          <T medium style={{ color: colors.onBlue, fontSize: 22 }}>{(user?.name ?? "?").slice(0, 1).toUpperCase()}</T>
        </View>
        <View style={{ flex: 1, gap: 2 }}>
          <T medium style={s.hello}>{user?.name}</T>
          <T style={s.muted} numberOfLines={1}>{user?.email}</T>
          {!!user?.neighbourhood && <T style={s.muted}>📍 {user.neighbourhood}</T>}
        </View>
      </View>

      {/* Main buttons */}
      <View style={s.group}>
        <Row
          icon="document-text"
          color={colors.blue}
          label={t("tabMine")}
          value={drafts.length ? t("draftsWaiting", { n: drafts.length }) : t("openOfTotal", { o: open, n: reports.length })}
          onPress={() => router.push("/my-reports")}
        />
        <Row
          icon="hammer"
          color={colors.orange}
          label={t("tabFix")}
          value={fixer ? t("fixerBadges", { n: fixer.verified }) : undefined}
          onPress={() => router.push("/fix")}
        />
        <Row
          icon="construct"
          color={colors.blue}
          label={t("mjTitle")}
          value={user?.mjeshter_status === "approved" ? `✓ ${t("mjVerifiedShort")}` : user?.mjeshter_status === "pending" ? t("mjPendingShort") : undefined}
          onPress={() => router.push("/mjeshtrit")}
        />
        <Row
          icon="gift"
          color={colors.amber}
          label={t("rewardsTitle")}
          value={fixer ? t("rewardsBalance", { n: fixer.balance }) : undefined}
          onPress={() => router.push("/rewards")}
        />
        <Row icon="trail-sign" color={colors.fixed} label={t("stTitle")} onPress={() => router.push("/streets")} />
        <Row icon="briefcase" color={colors.blue} label={t("bkTitle")} onPress={() => router.push("/bookings")} />
        <Row icon="leaf" color={colors.orange} label={t("cuTitle")} onPress={() => router.push("/cleanups")} />
        <Row icon="play-circle" color={colors.amber} label={t("wcHowToRow")}
          onPress={showWelcome} last />
      </View>

      {/* Look and language */}
      <View style={s.group}>
        <View style={s.groupBody}>
          <Settings />
        </View>
      </View>

      {/* Neighbourhood */}
      <View style={s.group}>
        <Row
          icon="location"
          color={colors.fixed}
          label={t("myArea")}
          value={user?.neighbourhood ?? t("notSet")}
          onPress={() => setEditArea(!editArea)}
          chevron={editArea ? "chevron-down" : "chevron-forward"}
          last={!editArea}
        />
        {editArea && (
          <View style={s.groupBody}>
            <T style={s.muted}>{t("whereLiveHint")}</T>
            <AreaPicker value={user?.neighbourhood ?? null} onChange={chooseArea} />
          </View>
        )}
      </View>

      {/* Near-you alerts */}
      <View style={s.group}>
        <View style={s.groupBody}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            <Ionicons name={homeOn ? "notifications" : "notifications-outline"} size={20} color={homeOn ? colors.accent : colors.muted} />
            <T medium style={{ fontSize: 16, flex: 1 }}>{t("alertsTitle")}</T>
          </View>
          <T style={s.muted}>{t("alertsOn")}</T>
          <Button
            title={homeOn ? t("alertsOff") : t("alertsSetHere")}
            variant={homeOn ? "ghost" : "primary"}
            loading={homeBusy}
            onPress={() => setHome(!homeOn)}
            style={{ marginTop: 4, height: 44 }}
          />
        </View>
      </View>

      {/* Badges */}
      {badges.length > 0 && (
        <View style={s.group}>
          <View style={s.groupBody}>
            <T style={s.label}>{t("badges")} · {earned}/{badges.length}</T>
            <View style={s.badges}>
              {badges.map((b) => (
                <View key={b.key} style={[s.badge, !b.earned && { opacity: 0.45 }]} accessibilityLabel={t(`badge_${b.key}` as TKey)}>
                  <T style={{ fontSize: 24 }}>{BADGE_ICON[b.key] ?? "⭐"}</T>
                  <T medium style={s.badgeName} numberOfLines={2}>{t(`badge_${b.key}` as TKey)}</T>
                  {!b.earned && <T style={s.badgeProg}>{b.progress}/{b.goal}</T>}
                </View>
              ))}
            </View>
          </View>
        </View>
      )}

      <Pressable style={s.signOut} onPress={askSignOut} accessibilityRole="button">
        <Ionicons name="log-out-outline" size={20} color={colors.danger} />
        <T medium style={{ color: colors.danger, fontSize: 16 }}>{t("signOut")}</T>
      </Pressable>
      <T style={[s.muted, { textAlign: "center" }]}>MendMap {Constants.expoConfig?.version ?? ""}</T>
      <T style={[s.muted, { textAlign: "center", fontSize: 12, marginTop: -4 }]}>{t("madeBy", { name: "Denis Ibrahimi" })}</T>
    </ScrollView>
  );
}

/** One settings row: coloured icon, label, value on the right, chevron. */
function Row({
  icon, color, label, value, onPress, last, chevron = "chevron-forward",
}: {
  icon: keyof typeof Ionicons.glyphMap;
  color: string;
  label: string;
  value?: string;
  onPress: () => void;
  last?: boolean;
  chevron?: keyof typeof Ionicons.glyphMap;
}) {
  const { colors } = useTheme();
  const s = useStyles(makeStyles);
  return (
    <Pressable onPress={onPress} style={({ pressed }) => [s.row, !last && s.rowLine, pressed && { opacity: 0.6 }]} accessibilityRole="button">
      <View style={[s.rowIcon, { backgroundColor: color }]}>
        <Ionicons name={icon} size={18} color="#fff" />
      </View>
      <T medium style={{ flex: 1, fontSize: 16 }}>{label}</T>
      {!!value && <T style={[s.muted, { maxWidth: 150 }]} numberOfLines={1}>{value}</T>}
      <Ionicons name={chevron} size={18} color={colors.muted} />
    </Pressable>
  );
}

const makeStyles = (c: Palette) =>
  StyleSheet.create({
    profile: { padding: 16, borderRadius: 16, backgroundColor: c.surface, gap: 8, borderWidth: 1, borderColor: c.line },
    profileTop: { flexDirection: "row", alignItems: "center", marginBottom: 4 },
    hello: { fontSize: 20 },
    label: { color: c.muted, fontSize: 12, marginTop: 4, textTransform: "uppercase", letterSpacing: 0.6 },
    muted: { color: c.muted, fontSize: 13 },
    card: {
      flexDirection: "row", gap: 12, alignItems: "center", padding: 12, borderRadius: 16,
      backgroundColor: c.surface, borderWidth: 1, borderColor: c.line,
    },
    thumb: { width: 64, height: 64, borderRadius: 12, backgroundColor: c.surface2 },
    title: { fontSize: 16 },
    badges: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
    statGrid: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
    stat: { width: "47%", flexGrow: 1, padding: 14, borderRadius: 16, backgroundColor: c.surface, borderWidth: 1, borderColor: c.line, gap: 4 },
    meter: { height: 8, borderRadius: 4, backgroundColor: c.line, overflow: "hidden" },
    meterFill: { height: 8, borderRadius: 4, backgroundColor: c.orange },
    job: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", padding: 10, borderRadius: 12, backgroundColor: c.orange + "1f" },
    badge: { width: "31%", flexGrow: 1, alignItems: "center", gap: 4, padding: 10, borderRadius: 12, backgroundColor: c.surface2 },
    badgeName: { fontSize: 12, textAlign: "center" },
    badgeProg: { fontSize: 11, color: c.muted },
    empty: { flex: 1, alignItems: "center", justifyContent: "center", gap: 8, padding: 24 },
    avatar: { width: 52, height: 52, borderRadius: 26, alignItems: "center", justifyContent: "center", backgroundColor: c.blue, marginRight: 12 },
    group: { borderRadius: 16, backgroundColor: c.surface, borderWidth: 1, borderColor: c.line, overflow: "hidden" },
    groupBody: { padding: 16, gap: 8 },
    row: { flexDirection: "row", alignItems: "center", gap: 12, paddingHorizontal: 14, paddingVertical: 13 },
    rowLine: { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: c.line },
    rowIcon: { width: 30, height: 30, borderRadius: 8, alignItems: "center", justifyContent: "center" },
    signOut: {
      flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, height: 52, borderRadius: 16,
      backgroundColor: c.surface, borderWidth: 1, borderColor: c.danger + "55",
    },
  });
