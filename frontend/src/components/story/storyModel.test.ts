import { describe, expect, it } from "vitest";
import { compactNumber, discoverTagLink, entryLabel, isExperimentalSite, matchesChapter, relativeTime, siteLabel, storyFacts, toStoryView } from "./storyModel";
import type { DiscoveredNovel } from "../../types/discovery";
import type { Novel } from "../../types/novel";

const NOW = new Date("2026-10-08T12:00:00Z");

const catalog = {
  id: 4,
  title: "The Quiet Ledger",
  author: "Mara Thorne",
  source_url: "https://www.royalroad.com/fiction/4",
  novel_site: "royalroad",
  img_url: null,
  description: "Books.",
  word_count: 412000,
  chapter_count: 98,
  status: "Ongoing",
  updated_at: "2026-10-08T10:00:00Z",
  tags: ["Progression", { name: "Slow burn" }],
} as unknown as DiscoveredNovel;

describe("storyModel", () => {
  it("prefers the library copy and falls back to the catalog", () => {
    const novel = { id: 11, title: "", url: "https://x.test/the-quiet-ledger", metadata_id: 4, word_count: null, author: "M. Thorne" } as unknown as Novel;
    const view = toStoryView(catalog, novel);
    expect(view.title).toBe("The Quiet Ledger");
    expect(view.author).toBe("M. Thorne");
    expect(view.wordCount).toBe(412000);
    expect(view.tags).toEqual(["Progression", "Slow burn"]);
    expect(view.metadataId).toBe(4);
  });

  it("builds the facts line and leaves out missing values instead of N/A", () => {
    expect(storyFacts(toStoryView(catalog, null), NOW)).toEqual(["Ongoing", "98 chapters", "412k words", "updated 2 h ago"]);
    const sparse = toStoryView({ ...catalog, word_count: null, chapter_count: null, status: null, updated_at: "" } as DiscoveredNovel, null);
    expect(storyFacts(sparse, NOW)).toEqual([]);
  });

  it("formats numbers, times and sites", () => {
    expect(compactNumber(950)).toBe("950");
    expect(compactNumber(1200)).toBe("1.2k");
    expect(compactNumber(2_500_000)).toBe("2.5M");
    expect(relativeTime("2026-10-05T12:00:00Z", NOW)).toBe("3 days ago");
    expect(siteLabel("royalroad")).toBe("Royal Road");
    expect(isExperimentalSite("scribblehub")).toBe(true);
    expect(isExperimentalSite("royalroad")).toBe(false);
  });

  it("labels and searches chapters", () => {
    expect(entryLabel({ chapter_number: 3 })).toBe("Chapter 3");
    expect(entryLabel({ chapter_number: 3, category: "side_story" })).toBe("Side story");
    expect(matchesChapter({ chapter_number: 41, title: "Interest Compounds" }, "4")).toBe(true);
    expect(matchesChapter({ chapter_number: 41, title: "Interest Compounds" }, "compound")).toBe(true);
    expect(matchesChapter({ chapter_number: 41, title: "Interest Compounds" }, "9")).toBe(false);
  });

  it("links a tag to Discover filters", () => {
    const url = new URL(discoverTagLink("tag", "Slow burn"), "http://nexus.test");
    expect(url.pathname).toBe("/discover/all");
    expect(JSON.parse(url.searchParams.get("filters")!)).toEqual({ tag: ["Slow burn"] });
  });
});
