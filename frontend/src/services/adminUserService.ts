import apiClient from "./apiClient";
import type { SignupMode } from "./authService";
import type { ContentLimits } from "../types/household";

export type AdminUser = {
  id: number;
  username: string;
  is_admin: boolean;
  is_disabled: boolean;
  created_at: string | null;
  last_seen_at: string | null;
  active_sessions: number;
  content_limits?: ContentLimits | null;
};

export type Invite = {
  id: number;
  label: string | null;
  max_uses: number | null;
  use_count: number;
  expires_at: string | null;
  revoked_at: string | null;
  created_at: string | null;
  status: "active" | "expired" | "used" | "revoked";
  /** Only present in the response that created the invite. */
  code: string | null;
};

export type PasswordResetLink = { token: string; path: string; expires_at: string };

export const adminUserService = {
  users: async () => (await apiClient.get<AdminUser[]>("/admin/users")).data,
  updateUser: async (id: number, changes: { is_admin?: boolean; is_disabled?: boolean }) =>
    (await apiClient.patch<AdminUser>(`/admin/users/${id}`, changes)).data,
  deleteUser: async (id: number) => {
    await apiClient.delete(`/admin/users/${id}`);
  },
  passwordResetLink: async (id: number) =>
    (await apiClient.post<PasswordResetLink>(`/admin/users/${id}/password-reset`, {})).data,
  settings: async () => (await apiClient.get<{ signup_mode: SignupMode }>("/admin/settings")).data,
  updateSettings: async (signup_mode: SignupMode) =>
    (await apiClient.put<{ signup_mode: SignupMode }>("/admin/settings", { signup_mode })).data,
  invites: async () => (await apiClient.get<Invite[]>("/admin/invites")).data,
  createInvite: async (invite: { label?: string; max_uses: number | null; expires_in_days: number | null }) =>
    (await apiClient.post<Invite>("/admin/invites", invite)).data,
  revokeInvite: async (id: number) => (await apiClient.delete<Invite>(`/admin/invites/${id}`)).data,
};
