import { describe, expect, it } from "vitest";
import { buildSourceLinks, chapterSourceLabel } from "./sourceLinks";

describe("buildSourceLinks", () => {
  it("returns null for missing or unknown sites", () => {
    expect(buildSourceLinks({ site: null, url: "https://x.test/a" })).toBeNull();
    expect(buildSourceLinks({ site: "", url: "https://x.test/a" })).toBeNull();
  });

  it("builds open, comments and kudos links for AO3", () => {
    const links = buildSourceLinks({ site: "ao3", url: "https://archiveofourown.org/works/123#top" });
    expect(links?.siteName).toBe("Archive of Our Own");
    expect(links?.open).toEqual({ label: "Open on Archive of Our Own", href: "https://archiveofourown.org/works/123" });
    expect(links?.comments?.href).toBe("https://archiveofourown.org/works/123#comments");
    expect(links?.kudos).toEqual({ label: "Leave kudos on AO3", href: "https://archiveofourown.org/works/123" });
  });

  it("uses the fiction page for Royal Road with a comments fragment and no kudos", () => {
    const links = buildSourceLinks({ site: "royalroad", url: "https://www.royalroad.com/fiction/1/x" });
    expect(links?.open?.href).toBe("https://www.royalroad.com/fiction/1/x");
    expect(links?.comments?.href).toBe("https://www.royalroad.com/fiction/1/x#comments");
    expect(links?.kudos).toBeNull();
  });

  it("builds FanFiction.net reviews from the story id", () => {
    const fromId = buildSourceLinks({ site: "fanfiction", url: "https://www.fanfiction.net/s/555/1/x", storyId: 555 });
    expect(fromId?.comments?.href).toBe("https://www.fanfiction.net/r/555/");
    const fromUrl = buildSourceLinks({ site: "fanfiction", url: "https://www.fanfiction.net/s/777/2/y" });
    expect(fromUrl?.comments?.href).toBe("https://www.fanfiction.net/r/777/");
  });

  it("uses the thread or book page for forum and book sites", () => {
    for (const site of ["spacebattles", "sufficientvelocity", "questionablequesting", "webnovel", "scribblehub"]) {
      const links = buildSourceLinks({ site, url: "https://example.test/thread/1" });
      expect(links?.comments?.href).toBe("https://example.test/thread/1");
      expect(links?.kudos).toBeNull();
    }
  });

  it("omits links when the story URL is missing", () => {
    const links = buildSourceLinks({ site: "ao3", url: null });
    expect(links?.open).toBeNull();
    expect(links?.comments).toBeNull();
    expect(links?.kudos).toBeNull();
  });
});

describe("chapterSourceLabel", () => {
  it("names the site", () => {
    expect(chapterSourceLabel("royalroad")).toBe("Read this chapter on Royal Road");
    expect(chapterSourceLabel(null)).toBeNull();
  });
});
