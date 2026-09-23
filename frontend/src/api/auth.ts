/**
 * Code Sonar — user auth API client.
 *
 * New backend contract (built in parallel by a sibling agent):
 *   GET  /api/auth/github/login → 302 to GitHub OAuth
 *   GET  /api/auth/google/login → 302 to Google OAuth (callbacks 302 back to /app)
 *   GET  /api/auth/me          → {id, name, email, avatar_url, provider} or 401
 *   POST /api/auth/logout
 *   GET  /api/auth/repos       → [{id, full_name, name, pushed_at, private, default_branch}]
 */

export interface User {
  id: string;
  name: string;
  email: string;
  avatar_url: string | null;
  provider: "github" | "google" | string;
}

export interface RepoOption {
  id: number | string;
  full_name: string;
  name: string;
  pushed_at: string | null;
  private: boolean;
  default_branch: string;
}

export const GITHUB_LOGIN_URL = "/api/auth/github/login";
export const GOOGLE_LOGIN_URL = "/api/auth/google/login";

async function decode(res: Response, fallback: string): Promise<any> {
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new Error(data?.detail ?? `${fallback} (HTTP ${res.status})`);
  return data;
}

/**
 * Returns the signed-in user, or null when the session is absent (401).
 * Throws on real transport/server errors so the app can show a retry state.
 */
export async function fetchMe(): Promise<User | null> {
  const res = await fetch("/api/auth/me", { credentials: "same-origin" });
  if (res.status === 401) return null;
  return (await decode(res, "Failed to check sign-in state")) as User;
}

export async function logout(): Promise<void> {
  const res = await fetch("/api/auth/logout", {
    method: "POST",
    credentials: "same-origin",
  });
  await decode(res, "Sign-out failed");
}

export async function fetchAuthRepos(): Promise<RepoOption[]> {
  const res = await fetch("/api/auth/repos", { credentials: "same-origin" });
  const data = await decode(res, "Failed to load your repositories");
  return (data.repos ?? data ?? []) as RepoOption[];
}

/** Accept "owner/name" or a full GitHub URL; normalizes to "owner/name". */
export function normalizeRepoInput(raw: string): string {
  const trimmed = raw.trim().replace(/\/+$/, "");
  const match = trimmed.match(/github\.com[/:]([^/]+\/[^/]+?)(?:\.git)?$/i);
  if (match) return match[1];
  return trimmed;
}
