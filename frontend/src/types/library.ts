export interface Library {
  id: number;
  name: string;
  user_id: number;
  novel_count?: number;
  last_activity?: string;
}

export interface LibrarySummary extends Library {
  description?: string;
  accent_color?: string;
}
