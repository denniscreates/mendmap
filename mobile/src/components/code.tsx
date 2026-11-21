import { useEffect, useRef, useState, type ComponentRef } from "react";
import { Pressable, StyleSheet, TextInput, View } from "react-native";
import Animated, { useAnimatedStyle, useSharedValue, withSequence, withTiming } from "react-native-reanimated";
import { useStyles, useTheme, type Palette } from "../lib/theme";
import { T } from "./ui";

const LENGTH = 6;

/**
 * Six digit boxes over one hidden input, so typing, deleting, pasting and iOS's
 * "From Mail/Messages" code suggestion all just work.
 * Bump `shake` to shake the boxes (e.g. after a wrong code).
 */
export function CodeBoxes({
  value,
  onChange,
  error,
  shake,
  label,
}: {
  value: string;
  onChange: (v: string) => void;
  error?: boolean;
  shake: number;
  label: string;
}) {
  const { colors } = useTheme();
  const s = useStyles(makeStyles);
  const input = useRef<ComponentRef<typeof TextInput>>(null);
  const [focused, setFocused] = useState(true);
  const x = useSharedValue(0);

  useEffect(() => {
    if (!shake) return;
    x.value = withSequence(
      withTiming(-10, { duration: 50 }),
      withTiming(10, { duration: 50 }),
      withTiming(-7, { duration: 50 }),
      withTiming(7, { duration: 50 }),
      withTiming(0, { duration: 50 }),
    );
  }, [shake, x]);

  const shakeStyle = useAnimatedStyle(() => ({ transform: [{ translateX: x.value }] }));

  return (
    <Pressable onPress={() => input.current?.focus()} accessible={false}>
      <Animated.View style={[s.row, shakeStyle]}>
        {Array.from({ length: LENGTH }, (_, i) => {
          const active = focused && (i === value.length || (i === LENGTH - 1 && value.length === LENGTH));
          return (
            <View
              key={i}
              style={[
                s.box,
                active && { borderColor: colors.blue, borderWidth: 2 },
                error && { borderColor: colors.danger, borderWidth: 2 },
              ]}
            >
              <T medium style={s.digit}>{value[i] ?? ""}</T>
            </View>
          );
        })}
      </Animated.View>
      <TextInput
        ref={input}
        value={value}
        onChangeText={(v) => onChange(v.replace(/\D/g, "").slice(0, LENGTH))}
        keyboardType="number-pad"
        textContentType="oneTimeCode"
        autoComplete="one-time-code"
        maxLength={LENGTH}
        autoFocus
        caretHidden
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        style={s.hidden}
        accessibilityLabel={label}
      />
    </Pressable>
  );
}

const makeStyles = (c: Palette) =>
  StyleSheet.create({
    row: { flexDirection: "row", justifyContent: "space-between", gap: 8 },
    box: {
      flex: 1, aspectRatio: 0.82, maxHeight: 64, borderRadius: 14, alignItems: "center", justifyContent: "center",
      backgroundColor: c.surface, borderWidth: 1, borderColor: c.line,
    },
    digit: { fontSize: 26, color: c.text },
    // Invisible but still focusable and able to receive the iOS code suggestion.
    hidden: { position: "absolute", width: 1, height: 1, opacity: 0 },
  });
