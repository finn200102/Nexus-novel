import type { SupportLink } from "../lib/supportLinks";
import apiClient from "./apiClient";

export type FollowKind = "author" | "series";

/** A followed author page or series on one site. */
export interface CreatorFollow {
  id: number;
  kind: FollowKind;
  site: string;
  key: string;
  name: string | null;
  metadata_author_id: number | null;
  metadata_target_id: number | null;
  created_at: string | null;
}

export interface FollowRequest {
  kind: FollowKind;
  site: string;
  key: string;
  name?: string | null;
  metadata_author_id?: number | null;
}

/** A new work by a followed author, or a new entry in a followed series. */
export interface NewWork {
  id: number;
  event_type: "author_new_work" | "series_new_work";
  message: string;
  created_at: string;
  read_at: string | null;
  title: string | null;
  url: string | null;
  site: string | null;
  metadata_id: number | null;
  author: string | null;
  follow: { id: number; kind: FollowKind; name: string | null } | null;
}

export interface AuthorWork {
  metadata_id: number | null;
  title: string | null;
  site: string | null;
  url: string | null;
  img_url?: string | null;
  status?: string | null;
}

/** The same author name on one site. */
export interface AuthorProfile {
  id: number;
  site: string;
  name: string;
  key: string | null;
  followable: boolean;
  follow_id: number | null;
  last_checked_at: string | null;
  works: AuthorWork[];
}

export interface AuthorPageData {
  support_links?: SupportLink[];
  id: number;
  name: string;
  site: string;
  profiles: AuthorProfile[];
}

export const followService = {
  async list(): Promise<CreatorFollow[]> {
    return (await apiClient.get<CreatorFollow[]>("/following")).data;
  },
  async follow(request: FollowRequest): Promise<CreatorFollow> {
    return (await apiClient.post<CreatorFollow>("/following", request)).data;
  },
  async unfollow(followId: number): Promise<void> {
    await apiClient.delete(`/following/${followId}`);
  },
  async newWorks(): Promise<NewWork[]> {
    return (await apiClient.get<NewWork[]>("/following/new-works")).data;
  },
  async markNewWorksRead(eventIds?: number[]): Promise<void> {
    await apiClient.post("/following/new-works/read", eventIds ?? null);
  },
  async author(metadataAuthorId: number): Promise<AuthorPageData> {
    return (await apiClient.get<AuthorPageData>(`/following/authors/${metadataAuthorId}`)).data;
  },
};
