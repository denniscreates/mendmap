import { useEventListener } from "expo";
import { useVideoPlayer, VideoView } from "expo-video";
import { useCallback, useEffect, useRef } from "react";
import { Pressable, StyleSheet } from "react-native";
import Animated, { Easing, useAnimatedStyle, useSharedValue, withDelay, withTiming } from "react-native-reanimated";
import { scheduleOnRN } from "react-native-worklets";
import { useI18n } from "../lib/i18n";
import { T } from "./ui";

const INTRO = require("../../assets/video/intro.mp4");
const MAX_MS = 9500; // safety net if the video never reports its end

/**
 * The 3D intro: city at night → orange problem pins → the MendMap pin mends them
 * → logo + "Spot it. Snap it. Mended." Plays once per launch, tap to skip,
 * then fades into the app with Reanimated. Always on navy, like the video.
 */
export function Intro({ onDone }: { onDone: () => void }) {
  const { t } = useI18n();
  const finished = useRef(false);
  const opacity = useSharedValue(1);
  const skipOpacity = useSharedValue(0);

  const player = useVideoPlayer(INTRO, (p) => {
    p.loop = false;
    p.muted = true;
    p.play();
  });

  const finish = useCallback(() => {
    if (finished.current) return;
    finished.current = true;
    opacity.value = withTiming(0, { duration: 450, easing: Easing.out(Easing.cubic) }, (ok) => {
      if (ok) scheduleOnRN(onDone);
    });
  }, [onDone, opacity]);

  useEventListener(player, "playToEnd", finish);

  useEffect(() => {
    skipOpacity.value = withDelay(1200, withTiming(1, { duration: 400 }));
    const timer = setTimeout(finish, MAX_MS);
    return () => clearTimeout(timer);
  }, [finish, skipOpacity]);

  const fade = useAnimatedStyle(() => ({ opacity: opacity.value }));
  const skipStyle = useAnimatedStyle(() => ({ opacity: skipOpacity.value }));

  return (
    <Animated.View style={[StyleSheet.absoluteFill, styles.root, fade]}>
      <VideoView player={player} style={StyleSheet.absoluteFill} contentFit="cover" nativeControls={false} />
      <Animated.View style={[styles.skipWrap, skipStyle]}>
        <Pressable onPress={finish} hitSlop={16} style={styles.skip} accessibilityRole="button" accessibilityLabel={t("skip")}>
          <T medium style={styles.skipText}>{t("skip")}</T>
        </Pressable>
      </Animated.View>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  root: { backgroundColor: "#070d1f", zIndex: 100 },
  skipWrap: { position: "absolute", right: 20, bottom: 48 },
  skip: { paddingHorizontal: 16, paddingVertical: 8, borderRadius: 999, backgroundColor: "#ffffff22" },
  skipText: { color: "#fff" },
});
