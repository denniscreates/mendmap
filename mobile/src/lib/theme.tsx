import AsyncStorage from "@react-native-async-storage/async-storage";
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useColorScheme } from "react-native";

/** Brand font from the intro animation. Only regular and medium: no bold text in the app. */
export const fonts = {
  regular: "SpaceGrotesk_400Regular",
  medium: "SpaceGrotesk_500Medium",
};

export type Status = "reported" | "in_progress" | "fixed";
export type Palette = typeof dark;
export type ThemeMode = "system" | "light" | "dark";

const dark = {
  scheme: "dark" as "dark" | "light",
  bg: "#070d1f",
  surface: "#0e1834",
  surface2: "#18264a",
  line: "#24335c",
  text: "#e9edf7",
  muted: "#8d9ab8",
  blue: "#2f63f0",
  accent: "#6d95ff", // links, active tabs
  orange: "#f26a2e",
  amber: "#f5b638",
  danger: "#ff8a7a",
  onBlue: "#ffffff",
  card: "#0e1834ee",
  reported: "#f26a2e",
  in_progress: "#f5b638",
  fixed: "#6d95ff",
};

const light: Palette = {
  scheme: "light",
  bg: "#f4f6fb",
  surface: "#ffffff",
  surface2: "#eaeef7",
  line: "#d8dfec",
  text: "#0b1530",
  muted: "#5d6a87",
  blue: "#2f63f0",
  accent: "#2452d6",
  orange: "#e2571b",
  amber: "#c98a06",
  danger: "#c8372a",
  onBlue: "#ffffff",
  card: "#ffffffee",
  reported: "#e2571b",
  in_progress: "#c98a06",
  fixed: "#2452d6",
};

export const statusColor = (c: Palette, s: Status) => c[s];

const CATEGORY_EMOJI: Record<string, string> = {
  pothole: "🕳️",
  streetlight: "💡",
  dumping: "🗑️",
  other: "📍",
  accessibility: "♿",
};
export const emojiFor = (icon: string) => CATEGORY_EMOJI[icon] ?? "📍";

// ---------- provider ----------
const KEY = "mendmap.theme";
type ThemeState = { colors: Palette; mode: ThemeMode; setMode: (m: ThemeMode) => void };
const ThemeContext = createContext<ThemeState>({ colors: dark, mode: "system", setMode: () => {} });

export function ThemeProvider({ children }: { children: ReactNode }) {
  const system = useColorScheme();
  const [mode, setModeState] = useState<ThemeMode>("system");

  useEffect(() => {
    AsyncStorage.getItem(KEY).then((v) => {
      if (v === "light" || v === "dark" || v === "system") setModeState(v);
    });
  }, []);

  const value = useMemo<ThemeState>(() => {
    const scheme = mode === "system" ? (system === "light" ? "light" : "dark") : mode;
    return {
      colors: scheme === "light" ? light : dark,
      mode,
      setMode: (m) => {
        setModeState(m);
        AsyncStorage.setItem(KEY, m);
      },
    };
  }, [mode, system]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export const useTheme = () => useContext(ThemeContext);

/** Builds a StyleSheet from the current palette and rebuilds it only when the theme changes. */
export function useStyles<T>(make: (c: Palette) => T): T {
  const { colors } = useTheme();
  return useMemo(() => make(colors), [colors, make]);
}
