import Constants from "expo-constants";
import * as Device from "expo-device";
import * as Notifications from "expo-notifications";
import { Platform } from "react-native";
import { api } from "./api";

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldPlaySound: true,
    shouldSetBadge: false,
    shouldShowBanner: true,
    shouldShowList: true,
  }),
});

/**
 * Asks for notification permission and sends the Expo push token to the API,
 * so the city's status changes reach the citizen.
 * Remote push needs a development/production build (not Expo Go) and an EAS projectId.
 */
export async function registerForPush(): Promise<string | null> {
  if (!Device.isDevice) return null;

  if (Platform.OS === "android") {
    // Android 13+: the channel must exist before asking, or no prompt appears.
    await Notifications.setNotificationChannelAsync("status", {
      name: "Report status",
      importance: Notifications.AndroidImportance.HIGH,
      lightColor: "#2f63f0",
    });
  }

  let { status } = await Notifications.getPermissionsAsync();
  if (status !== "granted") ({ status } = await Notifications.requestPermissionsAsync());
  if (status !== "granted") return null;

  const projectId = Constants.expoConfig?.extra?.eas?.projectId ?? Constants.easConfig?.projectId;
  if (!projectId) {
    console.info("MendMap: no EAS projectId yet, skipping push token. Run `npx eas-cli init` to enable push.");
    return null;
  }
  try {
    const { data } = await Notifications.getExpoPushTokenAsync({ projectId });
    await api.setPushToken(data);
    return data;
  } catch (e) {
    console.info("MendMap: push token unavailable", e);
    return null;
  }
}
