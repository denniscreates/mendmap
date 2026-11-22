import Ionicons from "@expo/vector-icons/Ionicons";
import { useMemo, useState } from "react";
import { FlatList, Modal, Pressable, StyleSheet, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { LANG_NAME, useI18n, type Lang } from "../lib/i18n";
import { useStyles, useTheme, type Palette } from "../lib/theme";
import { Input, T } from "./ui";

/** Every language the app can show, each in its own name ("Shqip", "Italiano", …), English first. */
const ALL = Object.keys(LANG_NAME).sort((a, b) => (a === "en" ? -1 : b === "en" ? 1 : LANG_NAME[a].localeCompare(LANG_NAME[b])));

/**
 * The person's main language: a field that opens a searchable list. The phone's own language
 * and the local one are shown at the top, so most people find theirs without searching.
 */
export function LanguagePicker({ value, onChange }: { value: Lang | null; onChange: (l: Lang) => void }) {
  const { t, deviceLang, localLang } = useI18n();
  const { colors } = useTheme();
  const s = useStyles(makeStyles);
  const insets = useSafeAreaInsets();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");

  const list = useMemo(() => {
    const top = [...new Set([deviceLang, localLang, "en"].filter((l): l is Lang => !!l))];
    const rest = ALL.filter((l) => !top.includes(l));
    const all = [...top, ...rest];
    const needle = q.trim().toLowerCase();
    return needle ? all.filter((l) => LANG_NAME[l].toLowerCase().includes(needle) || l.startsWith(needle)) : all;
  }, [q, deviceLang, localLang]);

  const pick = (l: Lang) => {
    onChange(l);
    setOpen(false);
    setQ("");
  };

  return (
    <>
      <Pressable onPress={() => setOpen(true)} style={s.field} accessibilityRole="button" accessibilityLabel={t("mainLang")}>
        <Ionicons name="language" size={20} color={colors.accent} />
        <T medium style={{ flex: 1, fontSize: 16 }}>{value ? LANG_NAME[value] : t("mainLangPick")}</T>
        <Ionicons name="chevron-down" size={18} color={colors.muted} />
      </Pressable>

      <Modal visible={open} animationType="slide" transparent onRequestClose={() => setOpen(false)}>
        <View style={s.backdrop}>
          <View style={[s.sheet, { paddingBottom: insets.bottom + 10 }]}>
            <View style={s.head}>
              <T medium style={{ fontSize: 18, flex: 1 }}>{t("mainLang")}</T>
              <Pressable onPress={() => setOpen(false)} hitSlop={10} style={s.x} accessibilityRole="button" accessibilityLabel={t("wcClose")}>
                <Ionicons name="close" size={20} color={colors.text} />
              </Pressable>
            </View>
            <Input value={q} onChangeText={setQ} placeholder={t("langSearch")} autoCorrect={false} autoCapitalize="none" />
            <FlatList
              data={list}
              keyExtractor={(l) => l}
              keyboardShouldPersistTaps="handled"
              style={{ marginTop: 8 }}
              renderItem={({ item }) => (
                <Pressable onPress={() => pick(item)} style={({ pressed }) => [s.row, pressed && { opacity: 0.6 }]}
                  accessibilityRole="button" accessibilityState={{ selected: item === value }}>
                  <T style={{ flex: 1, fontSize: 16 }}>{LANG_NAME[item]}</T>
                  {item === value && <Ionicons name="checkmark" size={20} color={colors.accent} />}
                </Pressable>
              )}
              ListEmptyComponent={<T style={{ color: colors.muted, padding: 16 }}>{t("langNone")}</T>}
            />
          </View>
        </View>
      </Modal>
    </>
  );
}

const makeStyles = (c: Palette) =>
  StyleSheet.create({
    field: { flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: 14, paddingVertical: 13, borderRadius: 14, borderWidth: 1, borderColor: c.line, backgroundColor: c.surface },
    backdrop: { flex: 1, backgroundColor: "#00000088", justifyContent: "flex-end", alignItems: "center" },
    sheet: { width: "100%", maxWidth: 520, height: "80%", backgroundColor: c.bg, borderTopLeftRadius: 24, borderTopRightRadius: 24, padding: 16, gap: 8 },
    head: { flexDirection: "row", alignItems: "center" },
    x: { width: 34, height: 34, borderRadius: 999, alignItems: "center", justifyContent: "center", backgroundColor: c.surface2 },
    row: { flexDirection: "row", alignItems: "center", paddingVertical: 13, paddingHorizontal: 6, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: c.line },
  });
