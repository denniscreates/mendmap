import Ionicons from "@expo/vector-icons/Ionicons";
import { Redirect } from "expo-router";
import { useEffect, useState } from "react";
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Vibration, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { AreaPicker, ELSEWHERE } from "../components/area";
import { CodeBoxes } from "../components/code";
import { Button, Input, LogoPin, Segmented, T, Wordmark } from "../components/ui";
import { api } from "../lib/api";
import { useAuth, type Provider } from "../lib/auth";
import { LANG_NAME, useI18n, type Lang } from "../lib/i18n";
import { useStyles, useTheme, type Palette } from "../lib/theme";

/** form: email sign-in / sign-up · social: demo Google/Apple account · code: confirm the email */
type Step = "form" | "social" | "code";

// Server messages that mean "this code can't be used any more": clear the boxes.
const BAD_CODE = new Set(["Wrong code", "The code expired. Ask for a new one", "Too many tries. Ask for a new code"]);

const mmss = (sec: number) => `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;

export default function Login() {
  const { user, signIn, signUp, socialSignIn } = useAuth();
  const { t, tErr, lang, localLang, setLang } = useI18n();
  const { colors } = useTheme();
  const s = useStyles(makeStyles);
  const [step, setStep] = useState<Step>("form");
  const [mode, setMode] = useState<"login" | "register">("login");
  const [provider, setProvider] = useState<Provider | null>(null); // null = email sign-up
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [area, setArea] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [demoCode, setDemoCode] = useState<string | null>(null);
  const [existing, setExisting] = useState(false);
  const [resendAt, setResendAt] = useState(0);
  const [expiresAt, setExpiresAt] = useState(0);
  const [clock, setClock] = useState(Date.now());
  const [shake, setShake] = useState(0);
  const [codeError, setCodeError] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  // One clock tick a second while the code screen is open (resend wait and expiry).
  useEffect(() => {
    if (step !== "code") return;
    const id = setInterval(() => setClock(Date.now()), 1000);
    return () => clearInterval(id);
  }, [step]);

  if (user) return <Redirect href="/" />;

  const wait = Math.max(0, Math.ceil((resendAt - clock) / 1000));
  const left = Math.max(0, Math.ceil((expiresAt - clock) / 1000));
  const providerName = provider === "apple" ? "Apple" : "Google";

  const run = async (fn: () => Promise<void>) => {
    setError("");
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      const msg = (e as Error).message;
      setError(tErr(msg));
      if (step === "code" && BAD_CODE.has(msg)) {
        setCodeError(true);
        setShake((n) => n + 1);
        setCode("");
        Vibration.vibrate(200);
      }
    } finally {
      setBusy(false);
    }
  };

  const sendCode = (social: boolean) =>
    run(async () => {
      const sent = await api.sendOtp(email.trim(), social ? "social" : "register");
      const at = Date.now();
      setDemoCode(sent.demo_code);
      setExisting(sent.existing);
      setCode("");
      setCodeError(false);
      setResendAt(at + sent.resend_in * 1000);
      setExpiresAt(at + sent.expires_in * 1000);
      setClock(at);
      setStep("code");
    });

  const verify = (value = code) => {
    if (!/^\d{6}$/.test(value)) return setError(t("errCode"));
    if (left === 0) return setError(tErr("The code expired. Ask for a new one"));
    const home = area === ELSEWHERE ? null : area;
    return run(() =>
      provider
        ? socialSignIn(provider, name.trim(), email.trim(), home, value)
        : signUp(name.trim(), email.trim(), password, home, value),
    );
  };

  const submitForm = () => {
    setError("");
    if (mode === "register" && !name.trim()) return setError(t("errName"));
    if (!email.includes("@")) return setError(t("errEmail"));
    if (password.length < 6) return setError(t("errPassword"));
    if (mode === "login") return run(() => signIn(email.trim(), password));
    if (!area) return setError(t("errArea"));
    setProvider(null);
    sendCode(false);
  };

  const submitSocial = () => {
    setError("");
    if (!name.trim()) return setError(t("errName"));
    if (!email.includes("@")) return setError(t("errEmail"));
    sendCode(true);
  };

  const openSocial = (p: Provider) => {
    setProvider(p);
    setError("");
    setStep("social");
  };

  const back = () => {
    setError("");
    setStep(step === "code" && provider ? "social" : "form");
  };

  const onCode = (digits: string) => {
    setCode(digits);
    setCodeError(false);
    if (error) setError("");
    if (digits.length === 6 && !busy) verify(digits);
  };

  return (
    <SafeAreaView style={s.root}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }}>
        {step !== "form" && (
          <Pressable onPress={back} style={s.backBtn} hitSlop={10} accessibilityRole="button" accessibilityLabel={t("back")}>
            <Ionicons name="chevron-back" size={24} color={colors.text} />
            <T medium>{t("back")}</T>
          </Pressable>
        )}
        <ScrollView contentContainerStyle={s.scroll} keyboardShouldPersistTaps="handled">
          {localLang && step === "form" && (
            <View style={s.lang}>
              <Segmented<Lang>
                value={lang}
                onChange={setLang}
                options={[
                  { value: "en", label: LANG_NAME.en },
                  { value: localLang, label: LANG_NAME[localLang] },
                ]}
              />
            </View>
          )}

          {step === "form" && (
            <>
              <View style={s.hero}>
                <LogoPin size={72} />
                <Wordmark size={42} />
                <T style={s.tagline}>{t("tagline")}</T>
              </View>
              <View style={s.form}>
                {mode === "register" && <Input placeholder={t("yourName")} value={name} onChangeText={setName} autoComplete="name" />}
                <Input
                  placeholder={t("email")}
                  value={email}
                  onChangeText={setEmail}
                  autoCapitalize="none"
                  keyboardType="email-address"
                  autoComplete="email"
                />
                <View>
                  <Input
                    placeholder={t("password")}
                    value={password}
                    onChangeText={setPassword}
                    secureTextEntry={!showPassword}
                    autoCapitalize="none"
                    autoComplete={mode === "login" ? "current-password" : "new-password"}
                    onSubmitEditing={submitForm}
                    style={{ paddingRight: 52 }}
                  />
                  <Pressable
                    onPress={() => setShowPassword(!showPassword)}
                    style={s.eye}
                    hitSlop={8}
                    accessibilityRole="button"
                    accessibilityLabel={showPassword ? t("hidePassword") : t("showPassword")}
                  >
                    <Ionicons name={showPassword ? "eye-off-outline" : "eye-outline"} size={22} color={colors.muted} />
                  </Pressable>
                </View>
                {mode === "register" && (
                  <View style={{ gap: 6, marginTop: 4 }}>
                    <T medium>{t("whereLive")}</T>
                    <T style={s.muted}>{t("whereLiveHint")}</T>
                    <AreaPicker value={area} onChange={setArea} allowElsewhere />
                  </View>
                )}
                {!!error && <ErrorLine text={error} />}
                <Button title={mode === "login" ? t("signIn") : t("createAccount")} onPress={submitForm} loading={busy} />

                <View style={s.orRow}>
                  <View style={s.rule} />
                  <T style={s.muted}>{t("orContinue")}</T>
                  <View style={s.rule} />
                </View>
                <SocialButton provider="google" label={t("withGoogle")} onPress={() => openSocial("google")} />
                {/* Apple sign-in is an iPhone thing; Android users get Google only. */}
                {Platform.OS !== "android" && (
                  <SocialButton provider="apple" label={t("withApple")} onPress={() => openSocial("apple")} />
                )}

                <Pressable onPress={() => { setMode(mode === "login" ? "register" : "login"); setError(""); }} style={{ padding: 12 }}>
                  <T style={s.muted}>
                    {mode === "login" ? t("newHere") : t("haveAccount")}
                    <T medium style={s.link}>{mode === "login" ? t("createAnAccount") : t("signIn")}</T>
                  </T>
                </Pressable>
              </View>
            </>
          )}

          {step === "social" && provider && (
            <View style={s.form}>
              <View style={s.providerHead}>
                <View style={[s.providerIcon, provider === "apple" && { backgroundColor: colors.text }]}>
                  <Ionicons
                    name={provider === "apple" ? "logo-apple" : "logo-google"}
                    size={30}
                    color={provider === "apple" ? colors.bg : "#4285F4"}
                  />
                </View>
                <T medium style={{ fontSize: 22 }}>{t("socialTitle", { p: providerName })}</T>
              </View>
              <View style={s.demoBox}>
                <Ionicons name="information-circle" size={20} color={colors.accent} />
                <T style={{ flex: 1, color: colors.muted }}>{t("socialDemo", { p: providerName })}</T>
              </View>
              <Input placeholder={t("yourName")} value={name} onChangeText={setName} autoComplete="name" />
              <Input
                placeholder={t("socialEmail", { p: providerName })}
                value={email}
                onChangeText={setEmail}
                autoCapitalize="none"
                keyboardType="email-address"
                autoComplete="email"
                onSubmitEditing={submitSocial}
              />
              <View style={{ gap: 6, marginTop: 4 }}>
                <T medium>{t("whereLive")}</T>
                <T style={s.muted}>{t("socialAreaHint")}</T>
                <AreaPicker value={area} onChange={setArea} allowElsewhere />
              </View>
              {!!error && <ErrorLine text={error} />}
              <Button title={t("sendCode")} onPress={submitSocial} loading={busy} />
            </View>
          )}

          {step === "code" && (
            <View style={s.form}>
              <View style={s.mailIcon}>
                <Ionicons name="mail-open-outline" size={34} color={colors.blue} />
              </View>
              <T medium style={s.codeTitle}>{existing ? t("welcomeBack") : t("codeTitle")}</T>
              <T style={s.muted}>
                {t("codeSentTo")}
                <T medium>{email.trim()}</T>
              </T>
              {demoCode && (
                <View style={s.demoBox}>
                  <Ionicons name="key-outline" size={20} color={colors.accent} />
                  <View style={{ flex: 1 }}>
                    <T style={{ color: colors.muted, fontSize: 13 }}>{t("demoCodeIs")}</T>
                    <T medium style={s.demoCode}>{demoCode}</T>
                  </View>
                  <Pressable onPress={() => onCode(demoCode)} style={s.fillBtn} hitSlop={6} accessibilityRole="button">
                    <T medium style={{ color: colors.onBlue }}>{t("fillIn")}</T>
                  </Pressable>
                </View>
              )}
              <View style={{ marginTop: 6 }}>
                <CodeBoxes value={code} onChange={onCode} error={codeError} shake={shake} label={t("codeTitle")} />
              </View>
              <T style={[s.muted, { fontSize: 13 }, left === 0 && { color: colors.danger }]}>
                {left > 0 ? t("codeExpires", { t: mmss(left) }) : t("codeExpired")}
              </T>
              {!!error && <ErrorLine text={error} />}
              <Button title={t("verify")} onPress={() => verify()} loading={busy} disabled={code.length < 6} />
              <View style={s.codeLinks}>
                <Pressable onPress={back} hitSlop={8}>
                  <T medium style={s.link}>{t("changeEmail")}</T>
                </Pressable>
                {wait > 0 ? (
                  <T style={s.muted}>{t("resendIn", { n: wait })}</T>
                ) : (
                  <Pressable onPress={() => sendCode(!!provider)} hitSlop={8} disabled={busy}>
                    <T medium style={s.link}>{t("resendCode")}</T>
                  </Pressable>
                )}
              </View>
            </View>
          )}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

function ErrorLine({ text }: { text: string }) {
  const { colors } = useTheme();
  const s = useStyles(makeStyles);
  return (
    <View style={s.errorBox} accessibilityLiveRegion="polite">
      <Ionicons name="alert-circle" size={18} color={colors.danger} />
      <T style={{ color: colors.danger, flex: 1 }}>{text}</T>
    </View>
  );
}

function SocialButton({ provider, label, onPress }: { provider: Provider; label: string; onPress: () => void }) {
  const { colors } = useTheme();
  const s = useStyles(makeStyles);
  // Apple's style: black button in light mode, white in dark mode.
  const apple = provider === "apple";
  const dark = colors.scheme === "dark";
  const bg = apple ? (dark ? "#fff" : "#000") : colors.surface;
  const fg = apple ? (dark ? "#000" : "#fff") : colors.text;
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [s.social, { backgroundColor: bg, borderColor: apple ? bg : colors.line, opacity: pressed ? 0.8 : 1 }]}
      accessibilityRole="button"
    >
      <Ionicons name={apple ? "logo-apple" : "logo-google"} size={20} color={apple ? fg : "#4285F4"} />
      <T medium style={{ color: fg, fontSize: 16 }}>{label}</T>
    </Pressable>
  );
}

const makeStyles = (c: Palette) =>
  StyleSheet.create({
    root: { flex: 1, backgroundColor: c.bg },
    scroll: { flexGrow: 1, justifyContent: "center", padding: 24 },
    lang: { position: "absolute", top: 12, right: 24, width: 190 },
    backBtn: { flexDirection: "row", alignItems: "center", gap: 2, paddingHorizontal: 14, paddingTop: 8, alignSelf: "flex-start" },
    hero: { alignItems: "center", gap: 6, marginBottom: 28 },
    tagline: { color: c.muted, fontSize: 16 },
    form: { gap: 12 },
    errorBox: {
      flexDirection: "row", alignItems: "center", gap: 8, padding: 10, borderRadius: 12,
      borderWidth: 1, borderColor: c.danger,
    },
    muted: { color: c.muted, textAlign: "center" },
    link: { color: c.accent },
    eye: { position: "absolute", right: 14, top: 0, bottom: 0, justifyContent: "center" },
    orRow: { flexDirection: "row", alignItems: "center", gap: 10, marginVertical: 4 },
    rule: { flex: 1, height: StyleSheet.hairlineWidth, backgroundColor: c.line },
    social: {
      flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 10,
      height: 52, borderRadius: 14, borderWidth: 1,
    },
    providerHead: { alignItems: "center", gap: 12, marginBottom: 4 },
    providerIcon: {
      width: 64, height: 64, borderRadius: 32, alignItems: "center", justifyContent: "center",
      backgroundColor: c.surface, borderWidth: 1, borderColor: c.line,
    },
    demoBox: {
      flexDirection: "row", alignItems: "center", gap: 10, padding: 12,
      borderRadius: 14, backgroundColor: c.surface2, borderWidth: 1, borderColor: c.line,
    },
    demoCode: { fontSize: 24, letterSpacing: 6 },
    fillBtn: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: 999, backgroundColor: c.blue },
    mailIcon: {
      alignSelf: "center", width: 72, height: 72, borderRadius: 36, alignItems: "center", justifyContent: "center",
      backgroundColor: c.surface2,
    },
    codeTitle: { fontSize: 24, textAlign: "center" },
    codeLinks: { flexDirection: "row", justifyContent: "space-between", paddingHorizontal: 4, paddingTop: 4 },
  });
