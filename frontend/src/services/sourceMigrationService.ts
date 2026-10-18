import apiClient from "./apiClient";
import { accountStorage } from "./accountStorage";
import type { SourceMigrationStory, SourceMigrationChapter, SourceMigrationMapping, SourceMigrationPreviewInput, SourceMigrationCounts, SourceMigrationItem, SourceMigrationPreview, SourceMigrationRecord, SourceMigrationTargets, SourceMigrationChapters, SourceMigrationPage, SourceMigrationApplyInput, SourceMigrationUndoInput } from "../generated/api";
export type MigrationStory = SourceMigrationStory;
export type MigrationChapter = SourceMigrationChapter;
/** The editor always supplies an explicit target or skip; wire requests also allow the default. */
export type MigrationMapping = Required<SourceMigrationMapping>;
export type MigrationInput = Omit<SourceMigrationPreviewInput, "mappings"> & { mappings: MigrationMapping[] };
export type MigrationCounts = SourceMigrationCounts;
export type MigrationItem = SourceMigrationItem;
export type MigrationPreview = SourceMigrationPreview;
export type MigrationRecord = SourceMigrationRecord;
export type MigrationPage<T> = Pick<SourceMigrationTargets, "total" | "offset" | "limit"> & { items: T[] };
export type MigrationApply = Omit<SourceMigrationApplyInput, "mappings"> & { mappings: MigrationMapping[] };
export type MigrationUndo = SourceMigrationUndoInput;
export type MigrationIntent = { kind: "apply"; input: MigrationApply; acknowledged_id?: number } | { kind: "undo"; migration_id: number; source_novel_id: number; target_novel_id: number; input: MigrationUndo; acknowledged_id?: number };
const key = (novelId: number) => `source-migration-intent:${novelId}`;
const positive = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value) && value > 0;
const operation = (value: unknown): value is string => typeof value === "string" && value.length > 0 && value.length <= 128;
/** Only bounded identifiers and the reviewed operation are kept, inside account/instance storage. */
export function readMigrationIntent(novelId: number): MigrationIntent | null {
  try {
    const value = JSON.parse(accountStorage.getItem(key(novelId)) || "null");
    if (!value || !operation(value.input?.operation_id) || (value.acknowledged_id !== undefined && !positive(value.acknowledged_id))) return null;
    if (value.kind === "undo" && positive(value.migration_id) && positive(value.source_novel_id) && positive(value.target_novel_id) && [value.source_novel_id, value.target_novel_id].includes(novelId) && Number.isSafeInteger(value.input.expected_revision) && value.input.expected_revision >= 1)
      return { kind: "undo", migration_id: value.migration_id, source_novel_id: value.source_novel_id, target_novel_id: value.target_novel_id, input: { operation_id: value.input.operation_id, expected_revision: value.input.expected_revision }, ...(value.acknowledged_id ? { acknowledged_id: value.acknowledged_id } : {}) };
    const input = value.input;
    if (value.kind !== "apply" || input.source_novel_id !== novelId || !positive(input.target_novel_id) || input.target_novel_id === novelId || typeof input.review_token !== "string" || !input.review_token || input.review_token.length > 4096 || !Array.isArray(input.mappings) || input.mappings.length > 20000 || input.mappings.some((row: MigrationMapping) => !positive(row?.source_chapter_id) || (row.target_chapter_id !== null && !positive(row.target_chapter_id)))) return null;
    return { kind: "apply", input: { source_novel_id: novelId, target_novel_id: input.target_novel_id, review_token: input.review_token, operation_id: input.operation_id, mappings: input.mappings.map((row: MigrationMapping) => ({ source_chapter_id: row.source_chapter_id, target_chapter_id: row.target_chapter_id })) }, ...(value.acknowledged_id ? { acknowledged_id: value.acknowledged_id } : {}) };
  } catch { return null; }
}
export function saveMigrationIntent(novelId: number, value: MigrationIntent | null) {
  if (value) accountStorage.setItem(key(novelId), JSON.stringify(value));
  else accountStorage.removeItem(key(novelId));
}
export const sourceMigrationService = {
  async targets(novelId: number, q = "", offset = 0, limit = 20): Promise<SourceMigrationTargets> { return (await apiClient.get("/reader/source-migrations/targets", { params: { source_novel_id: novelId, q, offset, limit } })).data; },
  async chapters(novelId: number, offset = 0, limit = 100): Promise<SourceMigrationChapters> { return (await apiClient.get(`/reader/source-migrations/chapters/${novelId}`, { params: { offset, limit } })).data; },
  async preview(input: MigrationInput, offset = 0, limit = 100): Promise<MigrationPreview> { return (await apiClient.post("/reader/source-migrations/preview", input, { params: { offset, limit } })).data; },
  async apply(input: MigrationApply): Promise<MigrationRecord> { return (await apiClient.post("/reader/source-migrations/apply", input)).data; },
  async history(novelId: number, offset = 0, limit = 20): Promise<SourceMigrationPage> { return (await apiClient.get("/reader/source-migrations", { params: { novel_id: novelId, offset, limit } })).data; },
  async get(id: number): Promise<MigrationRecord> { return (await apiClient.get(`/reader/source-migrations/${id}`)).data; },
  async undo(id: number, input: MigrationUndo): Promise<MigrationRecord> { return (await apiClient.post(`/reader/source-migrations/${id}/undo`, input)).data; },
};
