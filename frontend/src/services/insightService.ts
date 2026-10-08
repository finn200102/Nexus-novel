import apiClient from "./apiClient";

export type InsightSignal = { family: string; value: string; confidence?: number; evidence: Record<string, unknown>; model_version: string };
export type InsightAnalysis = { state: "not_started" | "queued" | "running" | "completed" | "failed"; signals: InsightSignal[] };
export type SimilarNovel = { novel_id: number; title: string; author?: string; score: number; explanation: string; reasons?: string[] };
export type CanonicalWork = { id: number; title: string; editions: Array<{ id: number; novel_id: number; edition_kind: string; language?: string | null }> };
export type StoryCitation = { chapter: number; quote: string; note?: string; start_offset?: number; end_offset?: number; anchor_state?: "exact" | "ambiguous" | "unanchored"; evidence_hash?: string; source_fingerprint?: string };
export type StoryEntity = { name: string; kind: "location" | "faction" | "item" | "concept" | "creature" | "organization" | "event"; aliases?: string[]; description: string; citations: StoryCitation[]; confidence?: number };
export type StoryEvent = { title: string; summary: string; consequences?: string[]; state?: string; citations: StoryCitation[]; confidence?: number };
export type StoryTag = { label: string; category: string; citations: StoryCitation[]; confidence?: number };
export type StoryGuideCharacter = { name: string; aliases?: string[]; roles: string[]; importance?: string[]; descriptions: string[]; appearance?: string[]; personality?: string[]; goals?: string[]; status?: string[]; citations: StoryCitation[]; first_seen_chapter: number; last_seen_chapter: number; portrait?: { id: string; url: string; label: string } };
export type StoryClaim = { subject: string; subject_kind: string; predicate: string; object: string; state: string; citations: StoryCitation[]; confidence?: number };
export type GuideEntityIdentity = { id: string; name: string; kind: string; identity_state: "provisional" | "verified" | "ambiguous" | "merged" | "hidden"; review_state: "machine_suggested" | "approved" | "hidden"; first_chapter: number; last_chapter: number; aliases: string[]; mention_count: number };
export type GuideRelationship = { id: string; subject: string; object: string; relation: string; chapter: number; state: string; evidence: StoryCitation[] };
export type GuideLedgerItem = { id: string; subject_entity_id?: string | null; object_entity_id?: string | null; subject?: string; predicate?: string; object?: string; chapter?: number; state?: string; review_state?: "machine_suggested" | "approved" | "hidden" | "superseded"; qualifiers?: Record<string, string>; citations: StoryCitation[]; confidence?: number };
export type GuideProfile = { roles?: string[]; descriptions?: string[]; appearance?: string[]; personality?: string[]; status?: string[]; goals?: string[] };
export type GuideProjectionEntity = GuideEntityIdentity & { citations: StoryCitation[]; facts?: Record<string, GuideLedgerItem[]>; profile?: GuideProfile };
export type GuideEntityArticle = { safe_through_chapter: number; entity: GuideEntityIdentity & { mentions: Array<{ chapter: number; surface: string; state: string }> }; claims: Array<{ id: string; subject: string; predicate: string; object: string; chapter: number; state: string; review_state?: GuideLedgerItem["review_state"]; qualifiers?: Record<string, string>; confidence?: number; evidence: Array<{ chapter: number; preview: string; start_offset?: number; end_offset?: number; anchor_state?: StoryCitation["anchor_state"] }> }> };
export type GuideStorySignal = { family: string; label: string; confidence: number; chapter_count: number; first_seen_chapter: number; last_seen_chapter: number; evidence: StoryCitation[]; provenance: "chapter_analysis" };
export type GuideStoryThread = { id: string; kind: string; title: string; status: string; first_chapter: number; latest_chapter: number; latest_development: GuideLedgerItem; developments: GuideLedgerItem[]; evidence: StoryCitation[]; confidence: number };
export type GuideDossierQuality = { assertion_count?: number; citation_count?: number; exact_anchor_count?: number; ambiguous_anchor_count?: number; unanchored_anchor_count?: number; has_summary?: boolean; status?: "ready" | "partial" | "needs_evidence"; model_version?: string };
export type GuideChapterDossier = { chapter: number; summary: GuideLedgerItem[]; point_of_view: GuideLedgerItem[]; setting: GuideLedgerItem[]; events: GuideLedgerItem[]; scenes: GuideLedgerItem[]; tags: Record<string, GuideLedgerItem[]>; character_facts: GuideLedgerItem[]; relationships?: GuideLedgerItem[]; open_questions?: GuideLedgerItem[]; consequences?: GuideLedgerItem[]; character_updates?: GuideLedgerItem[]; world_updates?: GuideLedgerItem[]; revelations?: GuideLedgerItem[]; takeaways?: GuideLedgerItem[]; dossier?: { status?: "ready" | "partial" | "needs_evidence"; quality?: GuideDossierQuality; version?: string } };
export type GuideChapterArticle = { work_id: number; chapter: number; safe_through_chapter: number; status: "ready" | "partial" | "needs_evidence" | "pending" | "not_yet_read"; dossier: { version: string; quality: GuideDossierQuality; updated_at?: string } | null; assertions: Array<{ id: string; subject: string; predicate: string; object: string; chapter: number; state: string; review_state?: GuideLedgerItem["review_state"]; qualifiers?: Record<string, string>; confidence?: number; evidence: Array<{ chapter: number; preview: string; start_offset?: number; end_offset?: number; anchor_state?: StoryCitation["anchor_state"] }> }> };
export type GuideChanges = { work_id: number; from_chapter: number; through_chapter: number; count: number; changes: Record<"characters" | "world" | "relationships" | "revelations" | "consequences" | "takeaways", GuideLedgerItem[]> };
export type GuideEntityProfileArticle = { work_id: number; safe_through_chapter: number; entity: GuideProjectionEntity; profile: GuideProfile; facts: Record<string, GuideLedgerItem[]>; developments: GuideLedgerItem[] };
export type GuideRelationshipTimeline = { work_id: number; safe_through_chapter: number; timelines: Array<{ id: string; entities: string[]; current_state: GuideLedgerItem | null; developments: GuideLedgerItem[] }> };
export type GuideProjection = {
  projection_version: string; safe_through_chapter: number; unavailable?: boolean;
  coverage: { state?: "empty" | "analyzing" | "partial" | "ready" | "degraded"; safe_through_chapter?: number; analyzed_chapter_count?: number; materialized_chapter_count?: number; validated_dossier_count?: number; ready_dossier_count?: number; dossier_count?: number; downloaded_chapter_count?: number; ambiguous_anchor_count?: number; latest_materialization_version?: string; stale_reason?: string | null; chapters?: number; entities: number; characters: number; world_entries: number; assertions: number; relationships: number; citations: number; needs_review: number };
  overview: { story_so_far: GuideLedgerItem[]; active_threads?: GuideStoryThread[]; resolved_threads?: GuideStoryThread[]; story_signals?: GuideStorySignal[] };
  characters: GuideProjectionEntity[]; world: GuideProjectionEntity[];
  relationships: GuideLedgerItem[]; timeline: GuideLedgerItem[]; arcs?: GuideStoryThread[]; chapter_dossiers?: GuideChapterDossier[]; assertions: GuideLedgerItem[];
  reader_context?: { library_id: number; novel_id: number };
};
export type StoryGuide = { chapters_analyzed: number; through_chapter: number; coverage?: { claims: number; scenes: number; entities: number; citations: number }; provider?: string; model?: string; external_provider?: boolean; guide_status?: "empty" | "ready" | "queued" | "running" | "building" | "completed" | "failed"; guide_error?: string | null; unavailable?: boolean; encyclopedia?: { overview?: string; overview_citations?: StoryCitation[]; premise?: string; premise_citations?: StoryCitation[]; themes?: string[]; active_arcs?: StoryEvent[]; active_mysteries?: StoryEvent[]; current_state?: StoryClaim[]; character_notes?: StoryGuideCharacter[]; entities?: StoryEntity[]; relationships?: Array<{ subject: string; object: string; relation: string; detail: string; state?: string; citations: StoryCitation[] }>; timeline?: StoryEvent[] }; characters: StoryGuideCharacter[]; chapters: Array<{ chapter: number; title: string; chapter_summary: string; summary_citations?: StoryCitation[]; detailed_summary?: string; point_of_view: string; point_of_view_citations?: StoryCitation[]; setting: string; setting_citations?: StoryCitation[]; tags: StoryTag[]; events: StoryEvent[]; entities?: StoryEntity[]; open_threads?: string[]; scenes?: Array<{ title: string; setting?: string; point_of_view?: string; participants?: string[]; summary: string; citations: StoryCitation[] }>; claims?: StoryClaim[] }> };

export const insightService = {
  async analysis(metadataId: number): Promise<InsightAnalysis> {
    return (await apiClient.get(`/discovery/novels/${metadataId}/analysis`)).data;
  },
  async enqueue(metadataId: number): Promise<{ queued: boolean; job_id?: string | null }> {
    return (await apiClient.post(`/discovery/novels/${metadataId}/analysis/enqueue`)).data;
  },
  async similar(metadataId: number): Promise<{ results: SimilarNovel[] }> {
    return (await apiClient.get(`/discovery/novels/${metadataId}/similar`)).data;
  },
  async editions(metadataId: number): Promise<CanonicalWork> {
    return (await apiClient.get(`/discovery/novels/${metadataId}/editions`)).data;
  },
  async storyGuide(metadataId: number, throughChapter?: number): Promise<StoryGuide> {
    return (await apiClient.get(`/discovery/novels/${metadataId}/story-guide`, {
      params: throughChapter === undefined ? undefined : { through_chapter: Math.max(0, throughChapter) },
    })).data;
  },
  async storyGuideEntities(metadataId: number, throughChapter?: number): Promise<{ through_chapter: number; entities: GuideEntityIdentity[]; unavailable?: boolean }> {
    return (await apiClient.get(`/discovery/novels/${metadataId}/story-guide/entities`, {
      params: throughChapter === undefined ? undefined : { through_chapter: Math.max(0, throughChapter) },
    })).data;
  },
  async storyGuideRelationships(metadataId: number, throughChapter?: number): Promise<{ through_chapter: number; relationships: GuideRelationship[]; unavailable?: boolean }> {
    return (await apiClient.get(`/discovery/novels/${metadataId}/story-guide/relationships`, {
      params: throughChapter === undefined ? undefined : { through_chapter: Math.max(0, throughChapter) },
    })).data;
  },
  async storyGuideProjection(metadataId: number, throughChapter?: number): Promise<GuideProjection> {
    return (await apiClient.get(`/discovery/novels/${metadataId}/story-guide/projection`, {
      params: throughChapter === undefined ? undefined : { through_chapter: Math.max(0, throughChapter) },
    })).data;
  },
  async storyGuideChanges(metadataId: number, fromChapter: number, throughChapter?: number): Promise<GuideChanges> {
    return (await apiClient.get(`/discovery/novels/${metadataId}/story-guide/changes`, { params: { from_chapter: Math.max(0, fromChapter), ...(throughChapter === undefined ? {} : { through_chapter: Math.max(0, throughChapter) }) } })).data;
  },
  async storyGuideEntityProfile(metadataId: number, entityId: string, throughChapter?: number): Promise<GuideEntityProfileArticle> {
    return (await apiClient.get(`/discovery/novels/${metadataId}/story-guide/entities/${encodeURIComponent(entityId)}/profile`, { params: throughChapter === undefined ? undefined : { through_chapter: Math.max(0, throughChapter) } })).data;
  },
  async storyGuideRelationshipTimeline(metadataId: number, throughChapter?: number, entityId?: string): Promise<GuideRelationshipTimeline> {
    return (await apiClient.get(`/discovery/novels/${metadataId}/story-guide/relationships/timeline`, { params: { ...(throughChapter === undefined ? {} : { through_chapter: Math.max(0, throughChapter) }), ...(entityId ? { entity_id: entityId } : {}) } })).data;
  },
  async storyGuideChapterDossier(metadataId: number, chapter: number, throughChapter?: number): Promise<GuideChapterArticle> {
    return (await apiClient.get(`/discovery/novels/${metadataId}/story-guide/chapters/${chapter}`, {
      params: throughChapter === undefined ? undefined : { through_chapter: Math.max(0, throughChapter) },
    })).data;
  },
  async storyGuideEntityArticle(metadataId: number, entityId: string, throughChapter?: number): Promise<GuideEntityArticle> {
    return (await apiClient.get(`/discovery/novels/${metadataId}/story-guide/entities/${encodeURIComponent(entityId)}`, {
      params: throughChapter === undefined ? undefined : { through_chapter: Math.max(0, throughChapter) },
    })).data;
  },
  async backfillStoryGuide(metadataId: number): Promise<{ queued: number; already_known: number; chapter_count: number }> {
    return (await apiClient.post(`/discovery/novels/${metadataId}/story-guide/backfill`)).data;
  },
  async regenerateStoryGuide(metadataId: number, throughChapter?: number): Promise<{ id: string; status: string; through_chapter: number }> {
    return (await apiClient.post(`/discovery/novels/${metadataId}/story-guide/regenerate`, undefined, {
      params: throughChapter === undefined ? undefined : { through_chapter: Math.max(0, throughChapter) },
    })).data;
  },
  async createStoryGuidePortrait(metadataId: number, payload: { name: string; description: string }): Promise<{ id: string; status: string; reused: boolean }> {
    return (await apiClient.post(`/discovery/novels/${metadataId}/story-guide/characters/portrait`, payload)).data;
  },
};
