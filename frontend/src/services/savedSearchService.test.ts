import { beforeEach, expect, it, vi } from "vitest";
import apiClient from "./apiClient";
import { EMPTY_DISCOVERY_FILTERS, discoveryFilterParams } from "./discoveryFilters";
import { makeSavedSearchDefinition, savedSearchHref, savedSearchService, type SavedSearchDefinition } from "./savedSearchService";
vi.mock("./apiClient", () => ({ default: { post: vi.fn() } }));
const id = "e6b83f1a-3c11-4ae4-b605-6d55228999aa";
const base: SavedSearchDefinition = { version: 1, scope: "catalog", q: "Two worlds", site: "archive", similar_to: 7, filters: { ...EMPTY_DISCOVERY_FILTERS, tag: ["adventure"], sortBy: "title" } };
beforeEach(() => vi.clearAllMocks());
it("writes canonical IDs only in version two top-level fields without changing raw criteria", async () => {
  vi.mocked(apiClient.post).mockResolvedValue({ data: {} });
  await savedSearchService.create("Favorites", { ...base, filters: { ...base.filters, canonicalInclude: [id] } });
  expect(apiClient.post).toHaveBeenCalledWith("/saved-searches", { name: "Favorites", notify_on_match: false, definition: { version: 2, scope: "catalog", q: base.q, site: "archive", similar_to: 7, canonical_include: [id], canonical_exclude: [], filters: expect.objectContaining({ tag: ["adventure"], sortBy: "title" }) } });
  const body = vi.mocked(apiClient.post).mock.calls[0][1] as { definition: SavedSearchDefinition };
  expect(body.definition.filters).not.toHaveProperty("canonicalInclude");
});
it("reopens persisted canonical IDs with query, source, similarity, and exclusions intact", () => {
  const definition = { ...base, version: 2 as const, filters: { tag: ["adventure"], sortBy: "title" } as SavedSearchDefinition["filters"], canonical_include: [id], canonical_exclude: ["b7f5ab3b-2783-4cf7-87bd-f9e8cb5d4035"] };
  const url = new URL(savedSearchHref(definition), "https://nexus.example");
  expect(url.pathname).toBe("/discover/archive"); expect(url.searchParams.get("q")).toBe(base.q); expect(url.searchParams.get("similar_to")).toBe("7");
  const filters = JSON.parse(url.searchParams.get("filters")!);
  expect(discoveryFilterParams(filters)).toMatchObject({ canonical_include: [id], canonical_exclude: definition.canonical_exclude, tag: ["adventure"], sort_by: "title" });
});
it("preserves legacy version one wire shape and permits explicitly clearing reviewed criteria", () => {
  expect(makeSavedSearchDefinition(base)).not.toHaveProperty("canonical_include");
  expect(makeSavedSearchDefinition({ ...base, version: 2, canonical_include: [id], filters: { ...base.filters, canonicalInclude: [] } }).canonical_include).toEqual([]);
});
