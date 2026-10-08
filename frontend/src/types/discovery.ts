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

export interface DiscoveryFilters {
  tag: string[];
  tagMode: string;
  fandom: string[];
  genre: string[];
  excludeTag: string[];
  excludeFandom: string[];
  excludeGenre: string[];
  excludeAuthor: string[];
  excludeText: string[];
  language: string[];
  completeOnly: string;
  crossover: string;
  status: string;
  minWordCount: string;
  minFavorites: string;
  minFollows: string;
  minReviews: string;
  minChapterCount: string;
  maxWordCount: string;
  updatedSinceDays: string;
  label: string;
  labelOrigin: string;
  importState: string;
  sortBy: string;
  sortOrder: string;
}

export interface SiteInfo {
  id: string;
  name: string;
}

export interface FandomInfo {
  id: number;
  site: string;
  media_type: string;
  external_category_id: string | null;
  display_name: string;
  aliases: string[];
  story_count: number | null;
}
