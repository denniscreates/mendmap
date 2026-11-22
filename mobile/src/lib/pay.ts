import { initPaymentSheet, initStripe, presentPaymentSheet } from "@stripe/stripe-react-native";
import Constants from "expo-constants";
import * as Linking from "expo-linking";
import type { PayInfo } from "./api";

/** Must match "merchantIdentifier" of the Stripe plugin in app.json (Apple Pay). */
const APPLE_MERCHANT_ID = "merchant.app.mendmap";

/**
 * Stripe's payment sheet: card, plus Apple Pay on iPhone and Google Pay on Android when the phone has them.
 * Apple Pay and Google Pay only show in a development or store build, not in Expo Go; cards work everywhere.
 * Returns false if the person closed the sheet without paying.
 */
export async function payWithStripe(p: PayInfo): Promise<boolean> {
  if (!p.client_secret || !p.publishable_key) throw new Error("Payments aren't set up on this server yet");
  // In Expo Go the deep-link path starts after "/--/".
  const urlScheme = Constants.appOwnership === "expo" ? Linking.createURL("/--/") : Linking.createURL("");
  await initStripe({ publishableKey: p.publishable_key, merchantIdentifier: APPLE_MERCHANT_ID, urlScheme });
  const init = await initPaymentSheet({
    merchantDisplayName: "MendMap",
    paymentIntentClientSecret: p.client_secret,
    returnURL: Linking.createURL("stripe-redirect"),
    applePay: { merchantCountryCode: p.merchant_country },
    googlePay: {
      merchantCountryCode: p.merchant_country,
      currencyCode: p.currency.toUpperCase(),
      testEnv: p.publishable_key.startsWith("pk_test"),
    },
  });
  if (init.error) throw new Error(init.error.message);
  const res = await presentPaymentSheet();
  if (res.error) {
    if (res.error.code === "Canceled") return false;
    throw new Error(res.error.message);
  }
  return true;
}
