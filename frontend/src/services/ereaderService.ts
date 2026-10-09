import apiClient from "./apiClient";

export type AppPasswordScope = "opds" | "kosync" | "extension";

export type AppPassword = {
  id: number;
  label: string;
  scope: AppPasswordScope;
  created_at: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
};

export type CreatedAppPassword = AppPassword & {
  /** Returned once; the server keeps only a hash. */
  secret: string;
};

export const ereaderService = {
  list: async () => (await apiClient.get<AppPassword[]>("/app-passwords")).data,
  create: async (label: string, scope: AppPasswordScope) =>
    (await apiClient.post<CreatedAppPassword>("/app-passwords", { label, scope })).data,
  revoke: async (id: number) => {
    await apiClient.delete(`/app-passwords/${id}`);
  },
};
