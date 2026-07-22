export interface Novel {
  id: number;
  title: string;
  url: string;
  description: string | null;
  cover_image: string | null;
  library_id: number;
  metadata_id: number | null;
  author: string | null;
  author_site_id: number | null;
  author_id: number | null;
  source_url: string | null;
  story_id: number | null;
  novel_site: string | null;
  img_url: string | null;
  word_count: number | null;
  reviews: number | null;
  favorites: number | null;
  follows: number | null;
  status: string | null;
  views: number | null;
  rating: number | null;
  publish_date: string | null;
  updated_date: string | null;
  chapter_count: number | null;
  analyzed_at: string | null;
  analysis_type: string | null;
  analyzed_chapter_count: number | null;
  parsed_at: string | null;
  created_at: string;
  updated_at: string;
  scrape_status?: "pending" | "completed" | "failed";
  scrape_error?: string | null;
  follow_state: "plan_to_read" | "reading" | "on_hold" | "completed" | "dropped" | "ignored";
  followed_at: string | null;
}

export interface NovelCreate {
  url: string;
  library_id: number;
}

export interface NovelListItem {
  id: number;
  title: string;
  author: string | null;
  source_url: string | null;
  novel_site: string | null;
  word_count: number | null;
  status: string | null;
  rating: number | null;
  img_url: string | null;
  created_at: string;
}

export interface NovelUpdateEvent {
  id: number;
  novel_id: number;
  event_type: string;
  chapter_count: number;
  first_chapter_number: number | null;
  last_chapter_number: number | null;
  message: string;
  details: Record<string, unknown>;
  created_at: string;
  read_at: string | null;
}
