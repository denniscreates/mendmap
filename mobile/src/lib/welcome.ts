import AsyncStorage from "@react-native-async-storage/async-storage";

/**
 * The welcome page (our ad + how to use the app). It opens on every launch after the intro,
 * until the person ticks "Don't show this again". Settings can open it again any time.
 */
const HIDE_KEY = "mendmap.welcome.hide";
const listeners = new Set<() => void>();

export async function welcomeHidden(): Promise<boolean> {
  return (await AsyncStorage.getItem(HIDE_KEY)) === "1";
}

export async function setWelcomeHidden(hide: boolean) {
  if (hide) await AsyncStorage.setItem(HIDE_KEY, "1");
  else await AsyncStorage.removeItem(HIDE_KEY);
}

/** Open the welcome page from anywhere (e.g. Settings → How MendMap works). */
export function showWelcome() {
  listeners.forEach((l) => l());
}

export function onShowWelcome(l: () => void) {
  listeners.add(l);
  return () => void listeners.delete(l);
}
