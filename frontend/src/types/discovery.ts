export interface DiscoveredNovel {
  id: number;
  title: string;
  author: string | null;
  author_id: number | null;
  source_url: string;
  novel_site: string;
  img_url: string | null;
  description: string | null;
  word_count: number | null;
  views: number | null;
  favorites: number | null;
  follows: number | null;
  reviews: number | null;
  status: string | null;
  rating: number | null;
  chapter_count: number | null;
  created_at: string;
  updated_at: string;
}

export interface PaginatedResponse<T> {
  data: T[];
  next_cursor: number | null;
  has_more: boolean;
}

export interface SiteInfo {
  id: string;
  name: string;
}
