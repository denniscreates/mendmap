import { SpaceGrotesk_400Regular, SpaceGrotesk_500Medium, useFonts } from "@expo-google-fonts/space-grotesk";
import * as Notifications from "expo-notifications";
import { router, Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { useEffect, useState } from "react";
import { Alert, View } from "react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { Intro } from "../components/Intro";
import { AuthProvider } from "../lib/auth";
import { startDraftSync } from "../lib/drafts";
import { I18nProvider, useI18n } from "../lib/i18n";
import { fonts, ThemeProvider, useTheme } from "../lib/theme";
import { installWebAlert } from "../lib/webAlert";

installWebAlert(); // browser: make "Are you sure?" dialogs work

export default function RootLayout() {
  const [fontsLoaded] = useFonts({ SpaceGrotesk_400Regular, SpaceGrotesk_500Medium });

  return (
    <SafeAreaProvider>
      <ThemeProvider>
        <I18nProvider>
          <AuthProvider>
            {/* The intro video covers the screen while the font loads. */}
            <Root fontsLoaded={fontsLoaded} />
          </AuthProvider>
        </I18nProvider>
      </ThemeProvider>
    </SafeAreaProvider>
  );
}

function Root({ fontsLoaded }: { fontsLoaded: boolean }) {
  const [showIntro, setShowIntro] = useState(true);
  const { colors } = useTheme();
  const { t } = useI18n();

  useEffect(() => {
    // Tapping a status notification opens that report.
    const sub = Notifications.addNotificationResponseReceivedListener((res) => {
      const data = res.notification.request.content.data;
      if (data?.reportId) router.push(`/report/${data.reportId}`);
      else if (data?.screen === "rewards") router.push("/rewards");
      else if (data?.screen === "mjeshtrit") router.push("/mjeshtrit");
      else if (data?.screen === "report" && data.id) router.push(`/report/${data.id}`);
      else if (data?.screen === "event" && data.id) router.push(`/cleanup/${data.id}`);
      else if (data?.screen === "booking" && data.id) router.push(`/booking/${data.id}`);
      else if (data?.screen === "chat" && data.room) router.push({ pathname: "/chat/[room]", params: { room: String(data.room) } });
    });
    return () => sub.remove();
  }, []);

  useEffect(() => {
    // Offline drafts are sent as soon as the phone is back online.
    return startDraftSync((n) => Alert.alert(t("backOnline"), t("backOnlineBody", { n })));
  }, [t]);

  return (
    <View style={{ flex: 1, backgroundColor: colors.bg }}>
      <StatusBar style={colors.scheme === "dark" ? "light" : "dark"} />
      {fontsLoaded && (
        <Stack
          screenOptions={{
            headerStyle: { backgroundColor: colors.surface },
            headerTintColor: colors.text,
            headerTitleStyle: { fontFamily: fonts.medium },
            headerBackTitleStyle: { fontFamily: fonts.regular },
            contentStyle: { backgroundColor: colors.bg },
          }}
        >
          <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
          <Stack.Screen name="login" options={{ headerShown: false, animation: "fade" }} />
          <Stack.Screen name="report/[id]" options={{ title: t("report") }} />
          <Stack.Screen name="my-reports" options={{ title: t("tabMine"), headerBackTitle: t("tabSettings") }} />
          <Stack.Screen name="rewards" options={{ title: t("rewardsTitle") }} />
          <Stack.Screen name="mjeshtrit" options={{ title: t("mjTitle") }} />
          <Stack.Screen name="mjeshter-apply" options={{ title: t("mjBecome") }} />
          <Stack.Screen name="chat/[room]" options={{ title: t("chatTitle"), headerBackTitle: t("tabChat") }} />
          <Stack.Screen name="cleanups" options={{ title: t("cuTitle") }} />
          <Stack.Screen name="cleanup-new" options={{ title: t("cuNew"), presentation: "modal" }} />
          <Stack.Screen name="cleanup/[id]" options={{ title: t("cuTitle") }} />
          <Stack.Screen name="streets" options={{ title: t("stTitle") }} />
          <Stack.Screen name="book" options={{ title: t("bkAsk"), presentation: "modal" }} />
          <Stack.Screen name="bookings" options={{ title: t("bkTitle") }} />
          <Stack.Screen name="booking/[id]" options={{ title: t("bkTitle") }} />
        </Stack>
      )}
      {(showIntro || !fontsLoaded) && <Intro onDone={() => setShowIntro(false)} />}
    </View>
  );
}
