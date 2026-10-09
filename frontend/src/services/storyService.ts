import { safeSupportLinks, type SupportLink } from "../lib/supportLinks";
import apiClient from "./apiClient";

/** One of the user's library copies of a catalog story. */
export interface LibraryEntry {
  novel_id: number;
  library_id: number;
  library_name: string;
  title: string;
  follow_state: string;
  scrape_status: string | null;
}

export interface StoryMembership {
  metadata_id: number;
  library_entries: LibraryEntry[];
  support_links: SupportLink[];
}

export const storyService = {
  /** Where a catalog story (metadata id) sits in the current user's libraries. */
  async membership(metadataId: number): Promise<StoryMembership> {
    const response = await apiClient.get<StoryMembership>(`/stories/${metadataId}`);
    return {
      metadata_id: metadataId,
      library_entries: response.data?.library_entries ?? [],
      support_links: safeSupportLinks(response.data?.support_links),
    };
  },
};
