import { useEffect, useState } from "react";
import { Pressable, StyleSheet, View } from "react-native";
import { api } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { useStyles, useTheme, type Palette } from "../lib/theme";
import { T } from "./ui";

/** Used when the server can't be reached; the server list is the source of truth. */
const FALLBACK = [
  "Arbëria", "Bregu i Diellit", "Dardania", "Gërmia", "Kalabria", "Lakrishte",
  "Mati 1", "Qendra", "Sofali", "Tophane", "Ulpiana",
];
export const ELSEWHERE = "__elsewhere__";

/** Neighbourhood chips: asked at sign-up so residents can take neighbour-fix jobs in their own area. */
export function AreaPicker({
  value,
  onChange,
  allowElsewhere,
}: {
  value: string | null;
  onChange: (v: string) => void;
  allowElsewhere?: boolean;
}) {
  const { colors } = useTheme();
  const { t } = useI18n();
  const s = useStyles(makeStyles);
  const [areas, setAreas] = useState<string[]>(FALLBACK);

  useEffect(() => {
    api.neighbourhoods().then(setAreas).catch(() => {});
  }, []);

  const options = allowElsewhere ? [...areas, ELSEWHERE] : areas;
  return (
    <View style={s.wrap}>
      {options.map((a) => {
        const on = a === value;
        return (
          <Pressable
            key={a}
            onPress={() => onChange(a)}
            style={[s.chip, on && { backgroundColor: colors.blue, borderColor: colors.blue }]}
            accessibilityRole="button"
            accessibilityState={{ selected: on }}
          >
            <T medium={on} style={{ fontSize: 14, color: on ? colors.onBlue : colors.text }}>
              {a === ELSEWHERE ? t("elsewhere") : a}
            </T>
          </Pressable>
        );
      })}
    </View>
  );
}

const makeStyles = (c: Palette) =>
  StyleSheet.create({
    wrap: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
    chip: { paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999, borderWidth: 1, borderColor: c.line, backgroundColor: c.surface },
  });
