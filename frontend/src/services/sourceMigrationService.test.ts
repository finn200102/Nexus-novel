import { beforeEach, expect, it, vi } from "vitest";
import { activateAccountStorage, accountStorage } from "./accountStorage";
import { readMigrationIntent, saveMigrationIntent, sourceMigrationService as service, type MigrationIntent } from "./sourceMigrationService";
import apiClient from "./apiClient";
vi.mock("./apiClient", () => ({ default: { get: vi.fn(), post: vi.fn() } }));
const intent: MigrationIntent = { kind: "apply", input: { source_novel_id: 11, target_novel_id: 22, review_token: "review", operation_id: "same-operation", mappings: [{ source_chapter_id: 101, target_chapter_id: null }] } };
beforeEach(() => { localStorage.clear(); activateAccountStorage(1); vi.clearAllMocks(); });
it("keeps a bounded operation in the account and instance namespace", () => {
  saveMigrationIntent(11, intent); expect(readMigrationIntent(11)).toEqual(intent); activateAccountStorage(2); expect(readMigrationIntent(11)).toBeNull(); activateAccountStorage(1); expect(readMigrationIntent(11)).toEqual(intent);
  accountStorage.setItem("source-migration-intent:11", JSON.stringify({ ...intent, input: { ...intent.input, source_novel_id: 12 } })); expect(readMigrationIntent(11)).toBeNull();
});
it("recovers an undo initiated from either side of the transfer without losing its source identity", () => {
  const undo: MigrationIntent = { kind: "undo", source_novel_id: 11, target_novel_id: 22, migration_id: 9, input: { operation_id: "undo-same", expected_revision: 3 } };
  saveMigrationIntent(22, undo); expect(readMigrationIntent(22)).toEqual(undo); saveMigrationIntent(33, undo); expect(readMigrationIntent(33)).toBeNull();
});
it("sends full-plan inputs unchanged while paging review and target chapter metadata separately", async () => {
  vi.mocked(apiClient.post).mockResolvedValue({ data: {} }); vi.mocked(apiClient.get).mockResolvedValue({ data: {} });
  await service.preview(intent.input, 200, 100); await service.chapters(22, 300, 100); await service.apply(intent.input);
  expect(apiClient.post).toHaveBeenNthCalledWith(1, "/reader/source-migrations/preview", intent.input, { params: { offset: 200, limit: 100 } }); expect(apiClient.get).toHaveBeenCalledWith("/reader/source-migrations/chapters/22", { params: { offset: 300, limit: 100 } }); expect(apiClient.post).toHaveBeenLastCalledWith("/reader/source-migrations/apply", intent.input);
});
it("recovers reviewed long-serial overrides above the former thousand-chapter limit", () => {
  const value: MigrationIntent = { ...intent, input: { ...intent.input, mappings: Array.from({ length: 1001 }, (_, index) => ({ source_chapter_id: index + 1, target_chapter_id: null })) } };
  saveMigrationIntent(11, value); expect(readMigrationIntent(11)?.kind).toBe("apply"); expect(readMigrationIntent(11)).toEqual(value);
});
