import { describe, expect, it } from "vitest";
import {
  EMPTY_DISCOVERY_FILTERS,
  discoveryFilterParams,
  isDiscoveryFilterActive,
  normalizeDiscoveryFilters,
} from "./discoveryFilters";

describe("normalizeDiscoveryFilters", () => {
  it("turns legacy single-string taxonomy filters into lists", () => {
    const filters = normalizeDiscoveryFilters({ tag: "time loop", genre: "", fandom: "Naruto" });
    expect(filters.tag).toEqual(["time loop"]);
    expect(filters.genre).toEqual([]);
    expect(filters.fandom).toEqual(["Naruto"]);
  });

  it("drops blanks and case-insensitive repeats", () => {
    const filters = normalizeDiscoveryFilters({ excludeTag: [" gore ", "", "Gore", "fluff"] });
    expect(filters.excludeTag).toEqual(["gore", "fluff"]);
  });

  it("falls back to defaults for unknown or malformed values", () => {
    const filters = normalizeDiscoveryFilters({ tagMode: "maybe", completeOnly: 1, crossover: "yes", excludeText: 42 });
    expect(filters.tagMode).toBe("all");
    expect(filters.completeOnly).toBe("");
    expect(filters.crossover).toBe("");
    expect(filters.excludeText).toEqual([]);
    expect(normalizeDiscoveryFilters(null)).toEqual(EMPTY_DISCOVERY_FILTERS);
  });

  it("round-trips a full filter set through JSON as used by the URL and saved searches", () => {
    const original = {
      ...EMPTY_DISCOVERY_FILTERS,
      tag: ["time loop", "academy"],
      tagMode: "any",
      excludeAuthor: ["Alice"],
      excludeText: ["gore"],
      language: ["English"],
      completeOnly: "true",
      crossover: "false",
    };
    const restored = normalizeDiscoveryFilters(JSON.parse(JSON.stringify(original)));
    expect(restored).toEqual(original);
  });
});

describe("isDiscoveryFilterActive", () => {
  it("ignores sort order and the default match mode", () => {
    expect(isDiscoveryFilterActive({ ...EMPTY_DISCOVERY_FILTERS, sortBy: "favorites", sortOrder: "asc" })).toBe(false);
    expect(isDiscoveryFilterActive({ ...EMPTY_DISCOVERY_FILTERS, tagMode: "any" })).toBe(false);
  });

  it("counts any exclusion, list or flag", () => {
    expect(isDiscoveryFilterActive({ ...EMPTY_DISCOVERY_FILTERS, excludeTag: ["gore"] })).toBe(true);
    expect(isDiscoveryFilterActive({ ...EMPTY_DISCOVERY_FILTERS, completeOnly: "true" })).toBe(true);
  });
});

describe("discoveryFilterParams", () => {
  it("emits repeated list keys and only the active scalar filters", () => {
    const params = discoveryFilterParams({
      ...EMPTY_DISCOVERY_FILTERS,
      tag: ["time loop", "academy"],
      tagMode: "any",
      excludeTag: ["character death"],
      excludeText: ["gore", "blood"],
      language: ["English"],
      completeOnly: "true",
      crossover: "true",
      minWordCount: "1000",
    });
    expect(params).toEqual({
      tag: ["time loop", "academy"],
      tag_mode: "any",
      exclude_tag: ["character death"],
      exclude_text: ["gore", "blood"],
      language: ["English"],
      complete_only: "true",
      crossover: "true",
      min_word_count: "1000",
      sort_by: "updated",
      sort_order: "desc",
    });
  });

  it("omits the all match mode and unchecked flags", () => {
    const params = discoveryFilterParams({ ...EMPTY_DISCOVERY_FILTERS, tag: ["x"], crossover: "" });
    expect(params).not.toHaveProperty("tag_mode");
    expect(params).not.toHaveProperty("complete_only");
    expect(params).not.toHaveProperty("crossover");
  });
});
