import Ionicons from "@expo/vector-icons/Ionicons";
import { useEventListener } from "expo";
import { useVideoPlayer, VideoView } from "expo-video";
import { useEffect, useState } from "react";
import { Platform, Pressable, StyleSheet, useWindowDimensions, View } from "react-native";
import Animated, { FadeIn, FadeOut } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useI18n } from "../lib/i18n";
import { useStyles, useTheme, type Palette } from "../lib/theme";
import { setWelcomeHidden } from "../lib/welcome";
import { Button, T } from "./ui";

const VIDEOS = [require("../../assets/video/ad.mp4"), require("../../assets/video/tutorial.mp4")];
const MAX_W = 960; // on a PC the videos play in a large card in the middle of the screen

/**
 * Opens right after the intro: our ad video, then the tutorial video (how to use the app).
 * The X closes it at any time; "Don't show this again" keeps it closed on the next launches.
 */
export function Welcome({ onClose }: { onClose: () => void }) {
  const { t } = useI18n();
  const { colors } = useTheme();
  const s = useStyles(makeStyles);
  const insets = useSafeAreaInsets();
  const { width, height } = useWindowDimensions();
  const wide = width > 700 && width > height;
  const cardW = wide ? Math.min(width - 64, MAX_W, (height - 230) * (16 / 9)) : width;
  const [page, setPage] = useState(0); // 0: the ad, 1: the tutorial
  const [hide, setHide] = useState(false);
  // The videos play with sound. Only if a browser refuses that (it often does before the first tap on a page)
  // they play muted, with a "Sound on" button.
  const [muted, setMuted] = useState(false);

  // One player per video. (Swapping the source of one player doesn't work on the web: the <video> reloads
  // on the next render and stops.) Only the player of the current page is on screen and playing.
  const setup = (p: { loop: boolean; muted: boolean }) => {
    p.loop = false;
    p.muted = false;
  };
  const ad = useVideoPlayer(VIDEOS[0], setup);
  const tutorial = useVideoPlayer(VIDEOS[1], setup);
  const player = page === 0 ? ad : tutorial;

  // Runs after the new VideoView is mounted (on the web play() only works on a <video> that is on screen).
  useEffect(() => {
    (page === 0 ? tutorial : ad).pause();
    const p = page === 0 ? ad : tutorial;
    p.replay(); // from the start
    if (Platform.OS !== "web") return;
    // The browser blocked playing with sound: the video stands still at 0. Play it muted instead.
    const check = setTimeout(() => {
      if (p.currentTime < 0.05 && p.status === "readyToPlay") {
        ad.muted = tutorial.muted = true;
        setMuted(true);
        p.play();
      }
    }, 1200);
    return () => clearTimeout(check);
  }, [page, ad, tutorial]);
  // Still loading when play() was called: start it once it can play.
  useEventListener(ad, "statusChange", ({ status }) => {
    if (status === "readyToPlay" && page === 0 && !ad.playing && ad.currentTime < 0.5) ad.play();
  });
  useEventListener(tutorial, "statusChange", ({ status }) => {
    if (status === "readyToPlay" && page === 1 && !tutorial.playing && tutorial.currentTime < 0.5) tutorial.play();
  });
  useEventListener(ad, "mutedChange", ({ muted: m }) => setMuted(m));
  useEventListener(tutorial, "mutedChange", ({ muted: m }) => setMuted(m));
  // The ad is over: go straight on to the tutorial.
  useEventListener(ad, "playToEnd", () => setPage(1));

  const show = (p: number) => setPage(p);
  const soundOn = () => {
    // eslint-disable-next-line react-hooks/immutability -- expo-video players are meant to be changed like this
    ad.muted = tutorial.muted = false;
    setMuted(false);
  };
  const close = () => {
    ad.pause();
    tutorial.pause();
    if (hide) void setWelcomeHidden(true);
    onClose();
  };

  return (
    <Animated.View entering={FadeIn.duration(350)} exiting={FadeOut.duration(250)} style={[StyleSheet.absoluteFill, s.backdrop]}>
      <View
        style={[
          s.card,
          wide
            ? { width: cardW, borderRadius: 24, borderWidth: 1, borderColor: colors.line }
            : { width, height: "100%", paddingTop: insets.top + 6, paddingBottom: insets.bottom + 6, justifyContent: "center" },
        ]}
        accessibilityViewIsModal
      >
        <View style={s.top}>
          <View style={s.tabs}>
            {[t("wcTabAd"), t("wcTabHow")].map((label, i) => (
              <Pressable key={label} onPress={() => i !== page && show(i)} style={[s.tab, i === page && s.tabOn]}
                accessibilityRole="tab" accessibilityState={{ selected: i === page }}>
                <Ionicons name={i === 0 ? "megaphone" : "school"} size={15} color={i === page ? "#fff" : colors.muted} />
                <T medium style={{ fontSize: 14, color: i === page ? "#fff" : colors.muted }}>{label}</T>
              </Pressable>
            ))}
          </View>
          <Pressable onPress={close} hitSlop={12} style={s.x} accessibilityRole="button" accessibilityLabel={t("wcClose")}>
            <Ionicons name="close" size={22} color={colors.text} />
          </Pressable>
        </View>

        <View style={[s.videoBox, { width: cardW }]}>
          <VideoView key={page} player={player} style={s.video} contentFit="contain" nativeControls
            fullscreenOptions={{ enable: true }} allowsPictureInPicture={false} />
          {muted && (
            <Pressable onPress={soundOn} style={s.sound} accessibilityRole="button" accessibilityLabel={t("wcSound")}>
              <Ionicons name="volume-high" size={18} color="#fff" />
              <T medium style={{ color: "#fff", fontSize: 14 }}>{t("wcSound")}</T>
            </Pressable>
          )}
        </View>

        <View style={s.footer}>
          <T style={s.caption}>{page === 0 ? t("wcAdTitle") : t("wcTutText")}</T>
          <Button
            title={page === 0 ? t("wcNextVideo") : t("wcStart")}
            variant={page === 0 ? "primary" : "orange"}
            onPress={() => (page === 0 ? show(1) : close())}
            icon={<Ionicons name={page === 0 ? "school" : "checkmark"} size={18} color="#fff" />}
          />
          <Pressable onPress={() => setHide(!hide)} style={s.hideRow} accessibilityRole="checkbox" accessibilityState={{ checked: hide }}>
            <Ionicons name={hide ? "checkbox" : "square-outline"} size={20} color={hide ? colors.accent : colors.muted} />
            <T style={s.muted}>{t("wcHide")}</T>
          </Pressable>
        </View>
      </View>
    </Animated.View>
  );
}

const makeStyles = (c: Palette) =>
  StyleSheet.create({
    backdrop: { zIndex: 90, backgroundColor: "#000000cc", alignItems: "center", justifyContent: "center" },
    card: { backgroundColor: c.bg, overflow: "hidden" },
    top: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 14, paddingVertical: 12, gap: 10 },
    tabs: { flexDirection: "row", gap: 6, flexShrink: 1 },
    tab: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999, backgroundColor: c.surface2 },
    tabOn: { backgroundColor: c.blue },
    x: { width: 38, height: 38, borderRadius: 999, alignItems: "center", justifyContent: "center", backgroundColor: c.surface2 },
    videoBox: { aspectRatio: 16 / 9, backgroundColor: "#000" },
    video: { position: "absolute", top: 0, left: 0, width: "100%", height: "100%" },
    sound: { position: "absolute", top: 12, right: 12, flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999, backgroundColor: "#000000aa" },
    footer: { paddingHorizontal: 18, paddingTop: 14, paddingBottom: 16, gap: 12 },
    caption: { textAlign: "center", color: c.muted, fontSize: 15 },
    hideRow: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, paddingVertical: 2 },
    muted: { color: c.muted, fontSize: 14 },
  });
