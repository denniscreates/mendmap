import type { PayInfo } from "./api";

/** Stripe's payment sheet only exists in the phone app. On the web, paying is done in the app. */
export async function payWithStripe(_p: PayInfo): Promise<boolean> {
  throw new Error("Paying works in the MendMap phone app");
}
