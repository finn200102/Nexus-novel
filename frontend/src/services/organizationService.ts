import apiClient from "./apiClient";
import type {
  BlocklistEntry,
  BlocklistKind,
  LibraryPersonalEntry,
  PersonalData,
  Shelf,
} from "../types/organization";

export const organizationService = {
  async listBlocklist(): Promise<BlocklistEntry[]> {
    return (await apiClient.get<BlocklistEntry[]>("/blocklist")).data;
  },
  async addBlocklistEntry(kind: BlocklistKind, value: string): Promise<BlocklistEntry> {
    return (await apiClient.post<BlocklistEntry>("/blocklist", { kind, value })).data;
  },
  async removeBlocklistEntry(id: number): Promise<void> {
    await apiClient.delete(`/blocklist/${id}`);
  },

  async listShelves(): Promise<Shelf[]> {
    return (await apiClient.get<Shelf[]>("/shelves")).data;
  },
  async createShelf(name: string): Promise<Shelf> {
    return (await apiClient.post<Shelf>("/shelves", { name })).data;
  },
  async renameShelf(id: number, name: string): Promise<Shelf> {
    return (await apiClient.patch<Shelf>(`/shelves/${id}`, { name })).data;
  },
  async deleteShelf(id: number): Promise<void> {
    await apiClient.delete(`/shelves/${id}`);
  },
  async addNovelToShelf(shelfId: number, novelId: number): Promise<Shelf> {
    return (await apiClient.put<Shelf>(`/shelves/${shelfId}/novels/${novelId}`)).data;
  },
  async removeNovelFromShelf(shelfId: number, novelId: number): Promise<Shelf> {
    return (await apiClient.delete<Shelf>(`/shelves/${shelfId}/novels/${novelId}`)).data;
  },

  async getPersonal(novelId: number): Promise<PersonalData> {
    return (await apiClient.get<PersonalData>(`/personal/novels/${novelId}`)).data;
  },
  // Partial update: only the fields passed are changed on the server.
  async savePersonal(
    novelId: number,
    data: Partial<{ notes: string | null; rating: number | null; user_tags: string[]; followed_categories: string[]; auto_download: boolean; keep_ahead: number }>,
  ): Promise<PersonalData> {
    return (await apiClient.put<PersonalData>(`/personal/novels/${novelId}`, data)).data;
  },
  async tagSuggestions(prefix: string): Promise<string[]> {
    const response = await apiClient.get<{ tags: string[] }>("/personal/tags", { params: { q: prefix } });
    return response.data.tags;
  },
  async libraryPersonal(libraryId: number): Promise<Record<string, LibraryPersonalEntry>> {
    const response = await apiClient.get<{ novels: Record<string, LibraryPersonalEntry> }>(`/personal/library/${libraryId}`);
    return response.data.novels;
  },
};
