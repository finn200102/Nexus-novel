import { describe, expect, it } from "vitest";
import { displayTitle } from "./displayTitle";

describe("displayTitle", () => {
  it("turns a stored URL slug into words", () => {
    expect(displayTitle({ title: "jim-the-groundskeeper-original-fantasy" })).toBe("Jim the Groundskeeper Original Fantasy");
  });

  it("decodes percent-encoded titles and never shows %XX", () => {
    const title = displayTitle({ title: "the-wrong-kind-of-immortality-%E2%80%94-original-fantasy" });
    expect(title).toBe("The Wrong Kind of Immortality \u2014 Original Fantasy");
    expect(title).not.toMatch(/%[0-9A-F]{2}/i);
  });

  it("strips the Threadmarks prefix", () => {
    expect(displayTitle({ title: "Threadmarks for: Mother of Learning" })).toBe("Mother of Learning");
  });

  it("derives the title from the URL when the stored title is empty or a placeholder", () => {
    expect(displayTitle({ title: "", url: "https://www.royalroad.com/fiction/21220/mother-of-learning" })).toBe("Mother of Learning");
    expect(displayTitle({ title: "Scraping...", url: "https://example.test/some-story" })).toBe("Some Story");
    expect(displayTitle({ title: null, url: null })).toBe("Untitled story");
  });

  it("keeps normal titles unchanged", () => {
    expect(displayTitle({ title: "Mother Of Learning", url: "https://x.test/a-b" })).toBe("Mother Of Learning");
  });
});
