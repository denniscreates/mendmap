import Ionicons from "@expo/vector-icons/Ionicons";
import * as Location from "expo-location";
import { router, useFocusEffect } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { Image, Pressable, ScrollView, StyleSheet, View } from "react-native";
import MapView, { Marker, type Region } from "../../components/Map";
import { SafeAreaView } from "react-native-safe-area-context";
import { MapPin, Segmented, StatusPill, T, useTimeAgo, Wordmark } from "../../components/ui";
import { api, photoUrl, type Category, type Report } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { jobState } from "../../lib/fixer";
import { categoryKey, useI18n } from "../../lib/i18n";
import { darkMapStyle } from "../../lib/mapStyle";
import { emojiFor, useStyles, useTheme, type Palette } from "../../lib/theme";

// Prishtina, Kosovo: where the demo reports are.
const FALLBACK: Region = { latitude: 42.6629, longitude: 21.1655, latitudeDelta: 0.05, longitudeDelta: 0.05 };
const CLOSE = { latitudeDelta: 0.012, longitudeDelta: 0.012 };

/** One simple status filter instead of three toggles: most people want what still needs fixing. */
type Show = "open" | "fixed" | "all";
const STATUS_PARAM: Record<Show, string> = {
  open: "reported,in_progress",
  fixed: "fixed",
  all: "reported,in_progress,fixed",
};

export default function MapScreen() {
  const mapRef = useRef<MapView>(null);
  const { user } = useAuth();
  const { colors } = useTheme();
  const { t, tErr, updateCountryFrom } = useI18n();
  const timeAgo = useTimeAgo();
  const s = useStyles(makeStyles);
  const [reports, setReports] = useState<Report[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [category, setCategory] = useState<number | null>(null);
  const [show, setShow] = useState<Show>("open");
  const [selected, setSelected] = useState<Report | null>(null);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const canReport = user?.role !== "crew";

  const goToMe = useCallback(async (ask: boolean) => {
    const perm = ask ? await Location.requestForegroundPermissionsAsync() : await Location.getForegroundPermissionsAsync();
    if (perm.status !== "granted") return;
    const pos = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
    mapRef.current?.animateToRegion({ ...pos.coords, ...CLOSE }, 600);
    updateCountryFrom(pos.coords); // picks the second language (e.g. Albanian in Kosovo)
  }, [updateCountryFrom]);

  useEffect(() => {
    api.categories().then(setCategories).catch(() => {});
    goToMe(true).catch(() => {});
  }, [goToMe]);

  const load = useCallback(async () => {
    try {
      setReports(await api.reports({ category: category ?? undefined, status: STATUS_PARAM[show] }));
      setError("");
    } catch (e) {
      setError(tErr((e as Error).message));
    } finally {
      setLoaded(true);
    }
  }, [category, show, tErr]);

  useFocusEffect(useCallback(() => void load(), [load]));

  const select = (r: Report) => {
    setSelected(r);
    // Centre the pin a little above the middle so the card below doesn't cover it.
    mapRef.current?.animateToRegion({ latitude: r.latitude - CLOSE.latitudeDelta * 0.15, longitude: r.longitude, ...CLOSE }, 400);
  };

  const resetFilters = () => {
    setCategory(null);
    setShow("all");
  };

  return (
    <View style={{ flex: 1 }}>
      <MapView
        ref={mapRef}
        style={StyleSheet.absoluteFill}
        initialRegion={FALLBACK}
        customMapStyle={colors.scheme === "dark" ? darkMapStyle : []}
        userInterfaceStyle={colors.scheme}
        showsUserLocation
        showsMyLocationButton={false}
        showsCompass={false}
        toolbarEnabled={false}
        onPress={() => setSelected(null)}
      >
        {reports.map((r) => (
          <Marker
            // The scheme in the key redraws the pins when the theme changes.
            key={`${r.id}-${colors.scheme}-${selected?.id === r.id}`}
            coordinate={{ latitude: r.latitude, longitude: r.longitude }}
            onPress={(e) => {
              e.stopPropagation();
              select(r);
            }}
            anchor={{ x: 0.5, y: 1 }}
            tracksViewChanges={false}
          >
            <MapPin status={r.status} icon={r.category.icon} selected={selected?.id === r.id} />
          </Marker>
        ))}
      </MapView>

      {/* Top: brand, one status switch, one row of categories */}
      <SafeAreaView edges={["top"]} style={s.top} pointerEvents="box-none">
        <View style={s.panel}>
          <View style={s.header}>
            <Wordmark size={22} />
            <View style={s.countPill}>
              <T medium style={s.countText}>{t("reportsCount", { n: reports.length })}</T>
            </View>
          </View>
          <Segmented<Show>
            value={show}
            onChange={(v) => { setShow(v); setSelected(null); }}
            options={[
              { value: "open", label: t("mapOpen") },
              { value: "fixed", label: t("fixed") },
              { value: "all", label: t("all") },
            ]}
          />
        </View>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chips}>
          <Chip label={t("allTypes")} active={category === null} onPress={() => setCategory(null)} />
          {categories.map((c) => (
            <Chip
              key={c.id}
              label={`${emojiFor(c.icon)} ${t(categoryKey(c.icon))}`}
              active={category === c.id}
              onPress={() => setCategory(category === c.id ? null : c.id)}
            />
          ))}
        </ScrollView>
        {!!error && <T style={s.error}>{error}</T>}
        {loaded && !error && reports.length === 0 && (
          <Pressable style={s.empty} onPress={resetFilters}>
            <T style={{ flex: 1 }}>{t("noneMatch")}</T>
            <T medium style={{ color: colors.accent }}>{t("showAll")}</T>
          </Pressable>
        )}
      </SafeAreaView>

      {/* Bottom: locate me, report button, or the selected report */}
      <View style={s.bottom} pointerEvents="box-none">
        <Pressable
          style={s.locate}
          onPress={() => goToMe(true).catch(() => {})}
          accessibilityRole="button"
          accessibilityLabel={t("locateMe")}
        >
          <Ionicons name="locate" size={24} color={colors.accent} />
        </Pressable>

        {selected ? (
          <Pressable style={s.card} onPress={() => router.push(`/report/${selected.id}`)} accessibilityRole="button">
            {selected.photo_url ? (
              <Image source={{ uri: photoUrl(selected.photo_url)! }} style={s.thumb} />
            ) : (
              <View style={[s.thumb, s.noThumb]}>
                <T style={{ fontSize: 28 }}>{emojiFor(selected.category.icon)}</T>
              </View>
            )}
            <View style={{ flex: 1, gap: 4 }}>
              <T medium style={s.cardTitle}>{emojiFor(selected.category.icon)} {t(categoryKey(selected.category.icon))}</T>
              <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
                <StatusPill status={selected.status} />
                {selected.flagged && (
                  <View style={[s.fixChip, { backgroundColor: colors.danger }]}>
                    <T medium style={{ color: "#fff", fontSize: 12 }}>⚠ {t("flagChip")}</T>
                  </View>
                )}
                {jobState(selected, user) === "ok" && (
                  <View style={s.fixChip}>
                    <T medium style={{ color: "#fff", fontSize: 12 }}>🛠️ {t("canFixChip")}</T>
                  </View>
                )}
              </View>
              <T style={s.cardMeta} numberOfLines={1}>
                {selected.neighbourhood ? `${selected.neighbourhood} · ` : ""}
                {timeAgo(selected.created_at)}
                {selected.confirmations > 0 ? ` · ${t("othersSeeIt", { n: selected.confirmations })}` : ""}
              </T>
              <T medium style={{ color: colors.accent, fontSize: 14 }}>{t("seeDetails")} ›</T>
            </View>
            <Pressable onPress={() => setSelected(null)} hitSlop={12} style={s.close} accessibilityLabel={t("cancel")}>
              <Ionicons name="close" size={20} color={colors.muted} />
            </Pressable>
          </Pressable>
        ) : (
          canReport && (
            <Pressable style={s.reportBtn} onPress={() => router.push("/report")} accessibilityRole="button">
              <Ionicons name="camera" size={22} color="#fff" />
              <T medium style={{ color: "#fff", fontSize: 16 }}>{t("reportProblem")}</T>
            </Pressable>
          )
        )}
      </View>
    </View>
  );
}

function Chip({ label, active, onPress }: { label: string; active: boolean; onPress: () => void }) {
  const { colors } = useTheme();
  const s = useStyles(makeStyles);
  return (
    <Pressable
      onPress={onPress}
      style={[s.chip, active && { backgroundColor: colors.blue, borderColor: colors.blue }]}
      accessibilityRole="button"
      accessibilityState={{ selected: active }}
    >
      <T medium style={[s.chipText, active && { color: colors.onBlue }]}>{label}</T>
    </Pressable>
  );
}

const shadow = (c: Palette) => ({
  shadowColor: "#000", shadowOpacity: c.scheme === "dark" ? 0.4 : 0.15, shadowRadius: 12, shadowOffset: { width: 0, height: 4 }, elevation: 6,
});

const makeStyles = (c: Palette) =>
  StyleSheet.create({
    top: { position: "absolute", top: 0, left: 0, right: 0 },
    panel: { marginHorizontal: 12, marginTop: 6, padding: 10, gap: 10, borderRadius: 18, backgroundColor: c.surface, ...shadow(c) },
    header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 4 },
    countPill: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 999, backgroundColor: c.surface2 },
    countText: { color: c.muted, fontSize: 13 },
    chips: { flexDirection: "row", gap: 8, paddingHorizontal: 12, paddingVertical: 10 },
    chip: {
      paddingHorizontal: 14, paddingVertical: 9, borderRadius: 999,
      backgroundColor: c.surface, borderWidth: 1, borderColor: c.line, ...shadow(c),
    },
    chipText: { color: c.text, fontSize: 14 },
    error: { color: c.danger, marginHorizontal: 12, backgroundColor: c.surface, padding: 10, borderRadius: 12 },
    empty: {
      flexDirection: "row", alignItems: "center", gap: 10, marginHorizontal: 12, padding: 12,
      borderRadius: 14, backgroundColor: c.surface, ...shadow(c),
    },
    bottom: { position: "absolute", left: 12, right: 12, bottom: 14, gap: 12, alignItems: "flex-end" },
    locate: {
      width: 52, height: 52, borderRadius: 26, alignItems: "center", justifyContent: "center",
      backgroundColor: c.surface, borderWidth: 1, borderColor: c.line, ...shadow(c),
    },
    reportBtn: {
      alignSelf: "stretch", flexDirection: "row", gap: 10, alignItems: "center", justifyContent: "center",
      height: 56, borderRadius: 28, backgroundColor: c.orange, ...shadow(c),
    },
    card: {
      alignSelf: "stretch", flexDirection: "row", gap: 12, alignItems: "center",
      padding: 12, borderRadius: 18, backgroundColor: c.surface, borderWidth: 1, borderColor: c.line, ...shadow(c),
    },
    close: { alignSelf: "flex-start", padding: 2 },
    fixChip: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999, backgroundColor: c.orange },
    thumb: { width: 84, height: 84, borderRadius: 12, backgroundColor: c.surface2 },
    noThumb: { alignItems: "center", justifyContent: "center" },
    cardTitle: { fontSize: 17 },
    cardMeta: { color: c.muted, fontSize: 13 },
  });
