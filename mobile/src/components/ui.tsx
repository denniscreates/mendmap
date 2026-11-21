import type { ReactNode } from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
  type StyleProp,
  type TextInputProps,
  type TextProps,
  type TextStyle,
  type ViewStyle,
} from "react-native";
import Svg, { Circle, Path } from "react-native-svg";
import { useI18n, type TKey } from "../lib/i18n";
import { emojiFor, fonts, statusColor, useTheme, type Status } from "../lib/theme";

/**
 * App text in the brand font (Space Grotesk). Two weights only, regular and medium:
 * there is no bold text anywhere in MendMap.
 */
export function T({ medium, style, ...rest }: TextProps & { medium?: boolean }) {
  const { colors } = useTheme();
  return (
    <Text
      {...rest}
      style={[{ color: colors.text, fontFamily: medium ? fonts.medium : fonts.regular }, style, noBold]}
    />
  );
}
// fontWeight is reset so a custom font is never synthetically bolded.
const noBold: TextStyle = { fontWeight: "normal" };

export function Input({ style, ...rest }: TextInputProps) {
  const { colors } = useTheme();
  return (
    <TextInput
      placeholderTextColor={colors.muted}
      selectionColor={colors.blue}
      keyboardAppearance={colors.scheme}
      {...rest}
      style={[
        {
          backgroundColor: colors.surface,
          borderColor: colors.line,
          borderWidth: 1,
          borderRadius: 14,
          color: colors.text,
          fontFamily: fonts.regular,
          fontSize: 16,
          paddingHorizontal: 16,
          height: 52,
        },
        style,
      ]}
    />
  );
}

/** The MendMap logo pin: blue drop with an orange wrench. */
export function LogoPin({ size = 48 }: { size?: number }) {
  const { colors } = useTheme();
  return (
    <Svg width={size} height={size * 1.25} viewBox="0 0 64 80">
      <Path d="M32 2C16 2 4 14 4 29c0 19 24 46 28 49 4-3 28-30 28-49C60 14 48 2 32 2z" fill={colors.blue} />
      <Circle cx={32} cy={29} r={17} fill="#EEF1F7" />
      <Path
        d="M38.5 18.5a7 7 0 0 0-8.6 8.9L21 36.3l3.7 3.7 8.9-8.9a7 7 0 0 0 8.9-8.6l-4 4-3.6-.4-.4-3.6z"
        fill="none"
        stroke={colors.orange}
        strokeWidth={3}
        strokeLinejoin="round"
      />
    </Svg>
  );
}

export function Wordmark({ size = 34 }: { size?: number }) {
  const { colors } = useTheme();
  return (
    <T medium style={{ fontSize: size, letterSpacing: -0.5 }}>
      Mend<T medium style={{ fontSize: size, color: colors.accent }}>Map</T>
    </T>
  );
}

/** Map marker: a drop pin coloured by status, with the category emoji. */
export function MapPin({ status, icon, selected }: { status: Status; icon: string; selected?: boolean }) {
  const { colors } = useTheme();
  const color = statusColor(colors, status);
  const s = selected ? 44 : 36;
  return (
    <View style={{ alignItems: "center", width: s, height: s * 1.25 }}>
      <Svg width={s} height={s * 1.25} viewBox="0 0 64 80" style={StyleSheet.absoluteFill}>
        <Path d="M32 2C16 2 4 14 4 29c0 19 24 46 28 49 4-3 28-30 28-49C60 14 48 2 32 2z" fill={color} stroke="#fff" strokeWidth={4} />
        <Circle cx={32} cy={29} r={17} fill="#fff" />
      </Svg>
      <Text style={{ marginTop: s * 0.2, fontSize: s * 0.36 }}>{emojiFor(icon)}</Text>
    </View>
  );
}

export function StatusPill({ status }: { status: Status }) {
  const { colors } = useTheme();
  const { t } = useI18n();
  const color = statusColor(colors, status);
  return (
    <View style={[styles.pill, { backgroundColor: color + "26" }]}>
      <View style={[styles.dot, { backgroundColor: color }]} />
      <T medium style={{ fontSize: 12, color }}>{t(status as TKey)}</T>
    </View>
  );
}

/** Small segmented control, used for the theme and language switches. */
export function Segmented<V extends string>({
  value,
  options,
  onChange,
}: {
  value: V;
  options: { value: V; label: string }[];
  onChange: (v: V) => void;
}) {
  const { colors } = useTheme();
  return (
    <View style={[styles.seg, { backgroundColor: colors.surface2 }]}>
      {options.map((o) => {
        const on = o.value === value;
        return (
          <Pressable
            key={o.value}
            onPress={() => onChange(o.value)}
            accessibilityRole="button"
            accessibilityState={{ selected: on }}
            style={[styles.segItem, on && { backgroundColor: colors.blue }]}
          >
            <T medium={on} style={{ fontSize: 14, color: on ? colors.onBlue : colors.muted }}>
              {o.label}
            </T>
          </Pressable>
        );
      })}
    </View>
  );
}

export function Button({
  title,
  onPress,
  variant = "primary",
  loading,
  disabled,
  style,
  icon,
}: {
  title: string;
  onPress: () => void;
  variant?: "primary" | "ghost" | "orange";
  loading?: boolean;
  disabled?: boolean;
  style?: StyleProp<ViewStyle>;
  icon?: ReactNode;
}) {
  const { colors } = useTheme();
  const bg = variant === "primary" ? colors.blue : variant === "orange" ? colors.orange : "transparent";
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled || loading}
      accessibilityRole="button"
      accessibilityState={{ disabled: !!(disabled || loading) }}
      style={({ pressed }) => [
        styles.btn,
        { backgroundColor: bg, opacity: disabled ? 0.45 : pressed ? 0.8 : 1 },
        variant === "ghost" && { borderWidth: 1, borderColor: colors.line },
        style,
      ]}
    >
      {loading ? (
        <ActivityIndicator color={variant === "ghost" ? colors.text : "#fff"} />
      ) : (
        <>
          {icon}
          <T medium style={{ fontSize: 16, color: variant === "ghost" ? colors.text : "#fff" }}>{title}</T>
        </>
      )}
    </Pressable>
  );
}

const parse = (iso: string) => new Date(iso.endsWith("Z") ? iso : iso + "Z");

/** "5 min ago" in the current language. */
export function useTimeAgo() {
  const { t, locale } = useI18n();
  return (iso: string) => {
    const d = parse(iso);
    const s = (Date.now() - d.getTime()) / 1000;
    if (s < 60) return t("justNow");
    if (s < 3600) return t("minAgo", { n: Math.round(s / 60) });
    if (s < 86400) return t("hAgo", { n: Math.round(s / 3600) });
    if (s < 86400 * 30) return t("dAgo", { n: Math.round(s / 86400) });
    return d.toLocaleDateString(locale);
  };
}

export function useFormatDate() {
  const { locale } = useI18n();
  return (iso: string) => {
    const d = parse(iso);
    try {
      return d.toLocaleString(locale, { dateStyle: "medium", timeStyle: "short" });
    } catch {
      return d.toLocaleString();
    }
  };
}

const styles = StyleSheet.create({
  pill: { flexDirection: "row", alignItems: "center", alignSelf: "flex-start", gap: 6, paddingHorizontal: 10, paddingVertical: 4, borderRadius: 999 },
  dot: { width: 7, height: 7, borderRadius: 4 },
  btn: { flexDirection: "row", gap: 8, height: 52, borderRadius: 14, alignItems: "center", justifyContent: "center", paddingHorizontal: 20 },
  seg: { flexDirection: "row", borderRadius: 12, padding: 3, gap: 3 },
  segItem: { flex: 1, alignItems: "center", paddingVertical: 8, borderRadius: 9 },
});
