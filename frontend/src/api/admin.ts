/**
 * Code Sonar — admin console API client (admin only).
 *
 *   GET  /api/admin/users                → {users, total}
 *   POST /api/admin/users/{id}/staff     → {user}
 *   POST /api/admin/users/{id}/admin     → {user}
 */

export interface AdminUserUsage {
  scans_used: number;
  ask_sonar_used: number;
}

export interface AdminUser {
  id: string;
  name: string;
  email: string;
  avatar_url: string | null;
  provider: string;
  plan: string;
  status: string;
  is_admin: boolean;
  is_staff: boolean;
  created_at: string;
  last_login_at: string;
  usage: AdminUserUsage;
}

async function decode(res: Response, fallback: string): Promise<any> {
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new Error(data?.detail ?? `${fallback} (HTTP ${res.status})`);
  return data;
}

export async function fetchAdminUsers(): Promise<{ users: AdminUser[]; total: number }> {
  const res = await fetch("/api/admin/users", { credentials: "same-origin" });
  return (await decode(res, "Failed to load users")) as { users: AdminUser[]; total: number };
}

export async function setUserStaff(id: string, isStaff: boolean): Promise<AdminUser> {
  const res = await fetch(`/api/admin/users/${encodeURIComponent(id)}/staff`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ is_staff: isStaff }),
  });
  const data = await decode(res, "Failed to update staff flag");
  return data.user as AdminUser;
}

export async function setUserAdmin(id: string, isAdmin: boolean): Promise<AdminUser> {
  const res = await fetch(`/api/admin/users/${encodeURIComponent(id)}/admin`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ is_admin: isAdmin }),
  });
  const data = await decode(res, "Failed to update admin flag");
  return data.user as AdminUser;
}
