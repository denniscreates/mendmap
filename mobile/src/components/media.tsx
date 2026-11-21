import Ionicons from "@expo/vector-icons/Ionicons";
import {
  RecordingPresets,
  requestRecordingPermissionsAsync,
  setAudioModeAsync,
  useAudioPlayer,
  useAudioPlayerStatus,
  useAudioRecorder,
  useAudioRecorderState,
} from "expo-audio";
import * as Sharing from "expo-sharing";
import { useEffect, useRef, useState, type ComponentRef, type Ref } from "react";
import { Alert, Image, Pressable, Share, StyleSheet, View } from "react-native";
import { captureRef } from "react-native-view-shot";
import { photoUrl, type Report } from "../lib/api";
import { categoryKey, useI18n } from "../lib/i18n";
import { emojiFor, statusColor, useStyles, useTheme, type Palette } from "../lib/theme";
import { LogoPin, StatusPill, T, Wordmark } from "./ui";

// ---------- voice note ----------
const secs = (ms: number) => Math.max(0, Math.round(ms / 1000));
export const MAX_VOICE_MS = 60_000;

/** Record a short voice note. Speech-to-text is left to the keyboard's dictation key. */
export function VoiceRecorder({ uri, onChange }: { uri: string | null; onChange: (uri: string | null) => void }) {
  const { colors } = useTheme();
  const { t } = useI18n();
  const s = useStyles(makeStyles);
  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);
  const state = useAudioRecorderState(recorder, 250);
  const [lengthMs, setLengthMs] = useState(0);

  const stop = async () => {
    await recorder.stop();
    await setAudioModeAsync({ allowsRecording: false, playsInSilentMode: true });
    setLengthMs(state.durationMillis);
    onChange(recorder.uri);
  };

  const start = async () => {
    const perm = await requestRecordingPermissionsAsync();
    if (!perm.granted) return Alert.alert(t("voiceNote"), t("micPerm"));
    await setAudioModeAsync({ allowsRecording: true, playsInSilentMode: true });
    await recorder.prepareToRecordAsync();
    recorder.record();
  };

  // Cap voice notes at one minute.
  useEffect(() => {
    if (state.isRecording && state.durationMillis >= MAX_VOICE_MS) void stop();
  }, [state.isRecording, state.durationMillis]); // eslint-disable-line react-hooks/exhaustive-deps

  if (uri && !state.isRecording) {
    return (
      <View style={s.voiceRow}>
        <VoicePlayer uri={uri} label={t("voiceSaved", { s: secs(lengthMs) })} />
        <Pressable onPress={() => onChange(null)} hitSlop={10} accessibilityLabel="Delete voice note" style={s.voiceDel}>
          <Ionicons name="trash-outline" size={20} color={colors.danger} />
        </Pressable>
      </View>
    );
  }
  return (
    <Pressable
      onPress={state.isRecording ? stop : start}
      style={[s.voiceBtn, state.isRecording && { borderColor: colors.orange, backgroundColor: colors.orange + "1f" }]}
      accessibilityRole="button"
    >
      <Ionicons name={state.isRecording ? "stop-circle" : "mic"} size={22} color={state.isRecording ? colors.orange : colors.accent} />
      <T medium style={{ color: state.isRecording ? colors.orange : colors.text, flex: 1 }}>
        {state.isRecording ? t("recording", { s: secs(state.durationMillis) }) : t("tapToRecord")}
      </T>
    </Pressable>
  );
}

export function VoicePlayer({ uri, label }: { uri: string; label?: string }) {
  const { colors } = useTheme();
  const { t } = useI18n();
  const s = useStyles(makeStyles);
  const player = useAudioPlayer(uri);
  const status = useAudioPlayerStatus(player);
  const progress = status.duration ? Math.min(1, status.currentTime / status.duration) : 0;

  const toggle = async () => {
    if (status.playing) return player.pause();
    await setAudioModeAsync({ playsInSilentMode: true });
    if (status.didJustFinish || (status.duration && status.currentTime >= status.duration - 0.1)) await player.seekTo(0);
    player.play();
  };

  return (
    <Pressable onPress={toggle} style={[s.voiceBtn, { flex: 1 }]} accessibilityRole="button" accessibilityLabel={t("playVoice")}>
      <Ionicons name={status.playing ? "pause-circle" : "play-circle"} size={26} color={colors.accent} />
      <View style={{ flex: 1, gap: 6 }}>
        <T medium style={{ fontSize: 14 }}>
          {label ?? t("playVoice")}
          {status.duration ? ` · ${Math.round(status.duration)}s` : ""}
        </T>
        <View style={s.track}>
          <View style={[s.trackFill, { width: `${progress * 100}%` }]} />
        </View>
      </View>
    </Pressable>
  );
}

// ---------- share card ----------
/** The image that gets shared: photo, category, area, status and how many neighbours confirmed it. */
type ViewHandle = ComponentRef<typeof View>;
export function ShareCard({ report, ref }: { report: Report; ref?: Ref<ViewHandle> }) {
  const { colors } = useTheme();
  const { t } = useI18n();
  const s = useStyles(makeStyles);
  const photo = photoUrl(report.photo_url);
  return (
    <View ref={ref} collapsable={false} style={s.card}>
      {photo && <Image source={{ uri: photo }} style={s.cardPhoto} />}
      <View style={{ padding: 16, gap: 8 }}>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
          <T style={{ fontSize: 22 }}>{emojiFor(report.category.icon)}</T>
          <T medium style={{ fontSize: 20, flex: 1 }}>{t(categoryKey(report.category.icon))}</T>
          <StatusPill status={report.status} />
        </View>
        {!!report.neighbourhood && <T style={{ color: colors.muted }}>📍 {report.neighbourhood}</T>}
        {report.confirmations > 0 && (
          <T style={{ color: statusColor(colors, report.status) }}>{t("shareCardSee", { n: report.confirmations })}</T>
        )}
        <View style={s.cardFoot}>
          <LogoPin size={22} />
          <Wordmark size={18} />
        </View>
      </View>
    </View>
  );
}

/** Snapshot the card and open the share sheet; falls back to a text share. */
export function useShareReport() {
  const { t } = useI18n();
  const ref = useRef<ViewHandle>(null);
  const share = async (report: Report) => {
    const message = t("shareMsg", { cat: t(categoryKey(report.category.icon)), area: report.neighbourhood ?? "Prishtina" });
    try {
      if (ref.current && (await Sharing.isAvailableAsync())) {
        const uri = await captureRef(ref, { format: "png", quality: 0.95, result: "tmpfile" });
        await Sharing.shareAsync(uri, { mimeType: "image/png", dialogTitle: message, UTI: "public.png" });
        return;
      }
    } catch {
      // fall through to text
    }
    await Share.share({ message });
  };
  return { ref, share };
}

const makeStyles = (c: Palette) =>
  StyleSheet.create({
    voiceRow: { flexDirection: "row", alignItems: "center", gap: 8 },
    voiceDel: { padding: 8 },
    voiceBtn: {
      flexDirection: "row", alignItems: "center", gap: 10, padding: 14, borderRadius: 14,
      backgroundColor: c.surface, borderWidth: 1.5, borderColor: c.line,
    },
    track: { height: 4, borderRadius: 2, backgroundColor: c.line, overflow: "hidden" },
    trackFill: { height: 4, backgroundColor: c.accent },
    card: { width: 340, borderRadius: 20, overflow: "hidden", backgroundColor: c.surface, borderWidth: 1, borderColor: c.line },
    cardPhoto: { width: 340, height: 255 },
    cardFoot: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 6 },
  });
