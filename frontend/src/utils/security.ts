/**
 * Defense-in-depth for browser-persisted scan data.
 *
 * The backend already redacts secret evidence server-side, but the frontend
 * persists scan results to localStorage (readable by any script on the
 * origin and by anyone with device access). These helpers make sure a
 * current or future analyzer can't land a secret, token, or credential in
 * persisted or rendered finding metadata just by adding a new metadata key.
 */

/** Metadata keys that must never be persisted or rendered verbatim. */
const SENSITIVE_KEY_PATTERN =
  /secret|token|credential|password|passwd|private[_-]?key|api[_-]?key|auth/i;

/**
 * Recursively strip sensitive keys from a value. Returns a sanitized copy;
 * primitives and arrays pass through (arrays are mapped element-wise).
 */
export function stripSensitiveKeys<T>(value: T): T {
  if (Array.isArray(value)) {
    return value.map(stripSensitiveKeys) as unknown as T;
  }
  if (value !== null && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [key, entry] of Object.entries(value as Record<string, unknown>)) {
      if (SENSITIVE_KEY_PATTERN.test(key)) continue;
      out[key] = stripSensitiveKeys(entry);
    }
    return out as unknown as T;
  }
  return value;
}

/** Stripe hosts the app is willing to navigate to for billing. */
const BILLING_HOSTS = new Set(["checkout.stripe.com", "billing.stripe.com"]);

/**
 * Validate a server-returned billing URL before navigating. An open redirect
 * at the moment the user expects to enter a card would be a perfect phish.
 */
export function assertBillingUrl(url: string): string {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    throw new Error("Unexpected billing URL");
  }
  if (parsed.protocol !== "https:" || !BILLING_HOSTS.has(parsed.hostname)) {
    throw new Error("Unexpected billing URL");
  }
  return parsed.toString();
}
