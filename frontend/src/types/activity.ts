export interface ActivityEvent {
  id: number;
  novel_id: number;
  novel_title: string;
  event_type: string;
  chapter_count: number;
  first_chapter_number: number | null;
  last_chapter_number: number | null;
  message: string;
  details: Record<string, unknown>;
  notification_visible: boolean;
  read_at: string | null;
  created_at: string;
}

export interface ActivityDay {
  date: string;
  event_count: number;
  chapter_count: number;
  stories_resumed: number;
  source_failures: number;
  downloads_completed: number;
}

export interface DownloadJob {
  id: number;
  library_id: number;
  novel_id: number;
  chapter_id: number;
  status: "queued" | "processing" | "retry_wait" | "completed" | "failed" | "cancelled";
  attempt_count: number;
  max_attempts: number;
  next_attempt_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  cancelled_at: string | null;
  cancellation_reason: string | null;
  error_code: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface InboxNovel {
  novel_id: number;
  title: string;
  new_chapter_count: number;
  first_new_chapter_number: number;
  latest_at: string;
  event_ids: number[];
  next_unread_chapter_id: number | null;
  next_unread_chapter_number: number | null;
}
