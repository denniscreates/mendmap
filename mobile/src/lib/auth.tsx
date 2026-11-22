import AsyncStorage from "@react-native-async-storage/async-storage";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, loadToken, setToken, setUnauthorizedHandler, type User } from "./api";
import { useI18n } from "./i18n";
import { registerForPush } from "./push";

const USER_KEY = "mendmap.user";

export type Provider = "google" | "apple";

type AuthState = {
  user: User | null;
  ready: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (name: string, email: string, password: string, neighbourhood: string | null, code: string, language: string | null) => Promise<void>;
  socialSignIn: (provider: Provider, name: string, email: string, neighbourhood: string | null, code: string, language: string | null) => Promise<void>;
  signOut: () => Promise<void>;
  /** Replace the signed-in user after a profile change (e.g. home area). */
  updateUser: (u: User) => void;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const { mainLang, setMainLang } = useI18n();

  // The account's main language wins: sign in on a new phone and the app speaks your language.
  useEffect(() => {
    if (user?.language && user.language !== mainLang) setMainLang(user.language);
  }, [user?.language]); // eslint-disable-line react-hooks/exhaustive-deps

  const signOut = useCallback(async () => {
    api.setPushToken(null).catch(() => {});
    await setToken(null);
    await AsyncStorage.removeItem(USER_KEY);
    setUser(null);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => void signOut());
    (async () => {
      const t = await loadToken();
      const cached = await AsyncStorage.getItem(USER_KEY);
      if (t && cached) {
        setUser(JSON.parse(cached));
        // Refresh in the background; works offline with the cached user.
        api.me().then(setUser).catch(() => {});
        registerForPush().catch(() => {});
      }
      setReady(true);
    })();
  }, [signOut]);

  const finish = async ({ token, user }: { token: string; user: User }) => {
    await setToken(token);
    await AsyncStorage.setItem(USER_KEY, JSON.stringify(user));
    setUser(user);
    registerForPush().catch(() => {});
  };

  const value = useMemo<AuthState>(
    () => ({
      user,
      ready,
      signIn: async (email, password) => finish(await api.login(email, password)),
      signUp: async (name, email, password, area, code, language) =>
        finish(await api.register(name, email, password, area, code, language)),
      socialSignIn: async (provider, name, email, area, code, language) =>
        finish(await api.social(provider, name, email, area, code, language)),
      signOut,
      updateUser: (u) => {
        setUser(u);
        AsyncStorage.setItem(USER_KEY, JSON.stringify(u));
      },
    }),
    [user, ready, signOut],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
