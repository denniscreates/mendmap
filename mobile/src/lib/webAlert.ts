import { Alert, Platform, type AlertButton } from "react-native";

/**
 * On the web, React Native's Alert.alert does nothing, so every "Are you sure?" (sign out, cancel a booking,
 * delete a message...) silently failed. This makes Alert.alert use the browser's own alert and confirm boxes.
 * Phones keep their native dialogs.
 */
export function installWebAlert() {
  if (Platform.OS !== "web" || typeof window === "undefined") return;
  Alert.alert = (title: string, message?: string, buttons?: AlertButton[]) => {
    const text = [title, message].filter(Boolean).join("\n\n");
    const list = buttons ?? [];
    const cancel = list.find((b) => b.style === "cancel");
    const actions = list.filter((b) => b !== cancel);
    if (actions.length <= 1 && !cancel) {
      window.alert(text);
      actions[0]?.onPress?.();
      return;
    }
    // One question per choice: "OK" picks it, "Cancel" moves on to the next one.
    for (const b of actions) {
      const ask = actions.length === 1 ? text : `${text}\n\n→ ${b.text ?? "OK"}?`;
      if (window.confirm(ask)) {
        b.onPress?.();
        return;
      }
    }
    cancel?.onPress?.();
  };
}
