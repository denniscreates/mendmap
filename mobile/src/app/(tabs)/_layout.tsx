import Ionicons from "@expo/vector-icons/Ionicons";
import { Redirect, Tabs } from "expo-router";
import { ActivityIndicator, View } from "react-native";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { fonts, useTheme } from "../../lib/theme";

export default function TabsLayout() {
  const { user, ready } = useAuth();
  const { colors } = useTheme();
  const { t } = useI18n();
  if (!ready)
    return (
      <View style={{ flex: 1, backgroundColor: colors.bg, justifyContent: "center" }}>
        <ActivityIndicator color={colors.accent} />
      </View>
    );
  if (!user) return <Redirect href="/login" />;
  // Crew sees its job route instead of the report button; admins get both.
  const crew = user.role === "crew" || user.role === "admin";
  const citizen = user.role !== "crew";

  return (
    <Tabs
      screenOptions={{
        headerStyle: { backgroundColor: colors.surface },
        headerTintColor: colors.text,
        headerTitleStyle: { fontFamily: fonts.medium },
        headerShadowVisible: false,
        tabBarStyle: { backgroundColor: colors.surface, borderTopColor: colors.line },
        tabBarLabelStyle: { fontFamily: fonts.medium },
        tabBarActiveTintColor: colors.accent,
        tabBarInactiveTintColor: colors.muted,
        sceneStyle: { backgroundColor: colors.bg },
      }}
    >
      <Tabs.Screen
        name="jobs"
        options={{
          title: t("tabJobs"),
          href: crew ? undefined : null,
          tabBarIcon: ({ color, size }) => <Ionicons name="construct" color={color as string} size={size} />,
        }}
      />
      <Tabs.Screen
        name="index"
        options={{
          title: t("tabMap"),
          headerShown: false,
          tabBarIcon: ({ color, size }) => <Ionicons name="map" color={color as string} size={size} />,
        }}
      />
      <Tabs.Screen
        name="report"
        options={{
          title: t("tabReport"),
          href: citizen ? undefined : null,
          headerTitle: t("newReport"),
          tabBarIcon: ({ size }) => (
            <View style={{ backgroundColor: colors.orange, borderRadius: 14, padding: 6, marginTop: -2 }}>
              <Ionicons name="camera" color="#fff" size={size - 4} />
            </View>
          ),
        }}
      />
      <Tabs.Screen
        name="fix"
        options={{
          title: t("tabFix"),
          headerTitle: t("fixTitle"),
          href: user.role === "citizen" ? undefined : null,
          tabBarIcon: ({ color, size }) => <Ionicons name="hammer" color={color as string} size={size} />,
        }}
      />
      <Tabs.Screen
        name="city"
        options={{
          title: t("tabCity"),
          tabBarIcon: ({ color, size }) => <Ionicons name="stats-chart" color={color as string} size={size} />,
        }}
      />
      <Tabs.Screen
        name="mine"
        options={{
          title: t("tabSettings"),
          tabBarIcon: ({ color, size }) => <Ionicons name="settings" color={color as string} size={size} />,
        }}
      />
    </Tabs>
  );
}
