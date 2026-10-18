import apiClient from "./apiClient";
import type { TermView, Scope, RawView, AuditView, Provenance, AliasView, AliasDecisionInput, TermPage, StoryScopeView, PreviewView, AliasCreate, TermCreate } from "../generated/api";
export type VocabularyKind = TermView["kind"];
export type VocabularyAction = AliasDecisionInput["action"];
export type VocabularyState = AliasView["state"];
export type VocabularyScope = Scope;
export type VocabularyTerm = TermView;
export type VocabularyRaw = RawView;
export type VocabularyAudit = AuditView;
export type VocabularyProvenance = Provenance;
export type VocabularyAlias = AliasView;
export type VocabularyPage<T> = Omit<TermPage,"items"> & {items:T[]};
export type VocabularyStoryScope = StoryScopeView;
export type VocabularyPreview = PreviewView;
export type VocabularyDecision = AliasDecisionInput;
export type VocabularyTermQuery = { kind?: VocabularyKind; ids?: string[]; q?: string; offset?: number; limit?: number; fandom_term_id?: string; story_key?: string };
const prefix = "/admin/vocabulary";
export const vocabularyService = {
  terms: async (params: VocabularyTermQuery, signal?: AbortSignal): Promise<VocabularyPage<VocabularyTerm>> => (await apiClient.get(`${prefix}/terms`, { params, signal, paramsSerializer: { indexes: null } })).data,
  readerTerms: async (params: VocabularyTermQuery, signal?: AbortSignal): Promise<VocabularyPage<VocabularyTerm>> => (await apiClient.get("/discovery/vocabulary/terms", { params, signal, paramsSerializer: { indexes: null } })).data,
  createTerm: async (input: TermCreate): Promise<VocabularyTerm> => (await apiClient.post(`${prefix}/terms`, input)).data,
  raw: async (params: { kind: VocabularyKind; q?: string; site?: string; offset?: number; limit?: number }, signal?: AbortSignal): Promise<VocabularyPage<VocabularyRaw>> => (await apiClient.get(`${prefix}/raw`, { params, signal, paramsSerializer: { indexes: null } })).data,
  stories: async (params: { q?: string; offset?: number; limit?: number }, signal?: AbortSignal): Promise<VocabularyPage<VocabularyStoryScope>> => (await apiClient.get(`${prefix}/story-scopes`, { params, signal, paramsSerializer: { indexes: null } })).data,
  aliases: async (params: { kind?: VocabularyKind; state?: VocabularyState; term_id?: string; offset?: number; limit?: number }): Promise<VocabularyPage<VocabularyAlias>> => (await apiClient.get(`${prefix}/aliases`, { params })).data,
  alias: async (id: string): Promise<VocabularyAlias> => (await apiClient.get(`${prefix}/aliases/${encodeURIComponent(id)}`)).data,
  propose: async (input: AliasCreate): Promise<VocabularyAlias> => (await apiClient.post(`${prefix}/aliases`, input)).data,
  preview: async (id: string, action: VocabularyAction): Promise<VocabularyPreview> => (await apiClient.post(`${prefix}/aliases/${encodeURIComponent(id)}/preview`, { action })).data,
  decide: async (id: string, input: VocabularyDecision): Promise<VocabularyAlias> => (await apiClient.post(`${prefix}/aliases/${encodeURIComponent(id)}/decide`, input)).data,
};

export const VOCABULARY_KINDS: VocabularyKind[] = ["fandom", "genre", "tag", "character", "relationship"];
export const termLabel = (term: VocabularyTerm) => `${term.display_name} · ${term.kind}${term.scope_label ? ` · ${term.scope_label}` : " · Global"}`;
