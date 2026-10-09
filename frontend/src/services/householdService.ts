import apiClient from "./apiClient";
import type {
  ContentLimits,
  SharePermission,
  ShareTarget,
  SharedShelfDetail,
  SharedShelfSummary,
  ShelfShares,
} from "../types/household";

export const householdService = {
  shareTargets: async () => (await apiClient.get<ShareTarget[]>("/shelves/share-targets")).data,
  shares: async (shelfId: number) => (await apiClient.get<ShelfShares>(`/shelves/${shelfId}/shares`)).data,
  share: async (shelfId: number, userId: number, permission: SharePermission) =>
    (await apiClient.put<ShelfShares>(`/shelves/${shelfId}/shares/${userId}`, { permission })).data,
  unshare: async (shelfId: number, userId: number) => {
    await apiClient.delete(`/shelves/${shelfId}/shares/${userId}`);
  },
  setShareNotes: async (shelfId: number, shareNotes: boolean) => {
    await apiClient.patch(`/shelves/${shelfId}`, { share_notes: shareNotes });
  },
  sharedWithMe: async () => (await apiClient.get<SharedShelfSummary[]>("/shelves/shared")).data,
  shelfStories: async (shelfId: number) => (await apiClient.get<SharedShelfDetail>(`/shelves/${shelfId}/stories`)).data,
  removeEntry: async (shelfId: number, entryId: number) =>
    (await apiClient.delete<SharedShelfDetail>(`/shelves/${shelfId}/entries/${entryId}`)).data,
  myLimits: async () => (await apiClient.get<{ content_limits?: ContentLimits | null }>("/auth/me")).data.content_limits ?? null,
  setLimits: async (userId: number, limits: Omit<ContentLimits, "limited">) =>
    (await apiClient.put<{ content_limits: ContentLimits }>(`/admin/users/${userId}/content-limits`, limits)).data,
};
