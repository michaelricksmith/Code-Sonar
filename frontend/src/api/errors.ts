/**
 * Code Sonar — shared API error type.
 *
 * ApiError extends the existing decode pattern (throw Error(data?.detail)
 * on !ok) by carrying the HTTP status and the parsed response body, so
 * callers can branch on specific failures — notably HTTP 402
 * {"upgrade_required": true, ...} quota responses from the billing layer.
 */

export interface QuotaErrorBody {
  upgrade_required?: boolean;
  kind?: "scans" | "ask_sonar" | string;
  plan?: string;
  limit?: number;
  used?: number;
}

export class ApiError extends Error {
  /** HTTP status code of the failed response. */
  status: number;
  /** Parsed JSON body when available, otherwise null. */
  body: unknown;

  constructor(status: number, message: string, body?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body ?? null;
  }

  /** True for the billing quota response: 402 + {"upgrade_required": true}. */
  get upgradeRequired(): boolean {
    if (this.status !== 402) return false;
    const b = this.body as QuotaErrorBody | null;
    return !!b && b.upgrade_required === true;
  }

  /** The quota kind when this is a quota error, otherwise null. */
  get quotaKind(): "scans" | "ask_sonar" | null {
    if (!this.upgradeRequired) return null;
    const kind = (this.body as QuotaErrorBody).kind;
    return kind === "scans" || kind === "ask_sonar" ? kind : null;
  }
}

/**
 * Typed decode: resolves with the parsed JSON on success, throws ApiError
 * (with status + body) on failure. Drop-in replacement for the per-client
 * `decode` helpers, which throw plain Errors.
 */
export async function decodeOrThrow(res: Response, fallback: string): Promise<any> {
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const detail =
      typeof data?.detail === "string"
        ? data.detail
        : typeof data?.error === "string"
          ? data.error
          : `${fallback} (HTTP ${res.status})`;
    throw new ApiError(res.status, detail, data);
  }
  return data;
}

/** True when `e` is a billing quota (402 upgrade_required) error. */
export function isQuotaError(e: unknown): e is ApiError {
  return e instanceof ApiError && e.upgradeRequired;
}
