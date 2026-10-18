import { createHash } from "node:crypto";
import { test, expect } from "./fixtures";
import type { Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import type { ChapterDocument } from "../src/components/reader/chapterDocument";

const chapterId = 9301, novelId = 93, libraryId = 1;
const path = `/library/${libraryId}/novels/${novelId}/1`;
const longParagraph = Array.from({ length: 1600 }, (_, index) => `Sentence ${index} follows the reader's progress through a very long paragraph.`).join(" ");
const makeDocument = (prefix = ""): ChapterDocument => {
  const texts = ["A short opening paragraph.", prefix + longParagraph, "The chapter ends here."];
  const blocks = texts.map(text => {
    const html = `<p>${text}</p>`;
    return { id: `b-${createHash("sha256").update(html).digest("hex").slice(0, 24)}-0`, kind: "p", html, text };
  });
  return { schema_version: 1, content_version: createHash("sha256").update(blocks.map(block => block.html).join("")).digest("hex"), source_format: "html", blocks, plain_text: texts.join("\n\n") };
};

async function fixture(page: Page) {
  let document = makeDocument();
  const original = document;
  const archives = new Map<string, ReturnType<typeof makeDocument>>();
  let failVersion = false;
  let progress: Record<string, unknown> | null = null;
  let saves = 0;
  const savedVersions: string[] = [];
  const annotations: Record<string, unknown>[] = [];
  await page.route(/127\.0\.0\.1:8000|localhost:8000|\/api\//, async route => {
    const url = new URL(route.request().url()).pathname.replace(/^\/api(?=\/)/, "");
    if (url === `/novel/${novelId}`) return route.fulfill({ json: { id: novelId, library_id: libraryId, title: "Locator fixture", author: "Fixture", total_chapters: 1 } });
    if (url === `/chapter/content/library/${libraryId}/${novelId}/1`) return route.fulfill({ json: { id: chapterId, novel_id: novelId, chapter_number: 1, title: "Long paragraph", document, content: document.plain_text } });
    if (url === `/chapter/${novelId}`) return route.fulfill({ json: [{ id: chapterId, chapter_number: 1, title: "Long paragraph", content_status: "PRESENT" }] });
    if (url === `/chapter/versions/${novelId}/1`) return route.fulfill({ json: { current_version: document.content_version, next_cursor: null,
      versions: [document, ...Array.from(archives.values()).filter(value => value.content_version !== document.content_version)].map(value => ({
        content_version: value.content_version, title: "Long paragraph", saved_at: "2026-10-14T16:00:00Z", byte_count: JSON.stringify(value).length,
        current: value.content_version === document.content_version, reason: "source_update" })) } });
    if (url.startsWith(`/chapter/versions/${novelId}/1/`)) {
      if (failVersion) { failVersion = false; return route.fulfill({ status: 503, json: { detail: "Temporary fixture failure" } }); }
      const hash = url.split("/").at(-1)!;
      const value = hash === document.content_version ? document : archives.get(hash);
      return value ? route.fulfill({ json: { id: chapterId, novel_id: novelId, chapter_number: 1, title: "Long paragraph", content: value.plain_text, document: value } }) : route.fulfill({ status: 404 });
    }
    if (url === `/chapter/progress/${novelId}`) {
      if (route.request().method() === "PUT") {
        const body = route.request().postDataJSON(); saves += 1;
        savedVersions.push(body.content_version);
        progress = { ...body, novel_id: novelId, revision: saves, locator_content_version: body.content_version, updated_at: new Date().toISOString() };
      }
      return route.fulfill({ json: progress });
    }
    if (url === `/chapter/annotations/${novelId}`) {
      if (route.request().method() === "POST") annotations.push({ id: annotations.length + 1, ...route.request().postDataJSON() });
      return route.fulfill({ json: route.request().method() === "POST" ? annotations[annotations.length - 1] : annotations });
    }
    if (url.startsWith("/audio/jobs")) return route.fulfill({ json: [] });
    if (url === "/reader/preferences" || url.startsWith("/reader/preferences/stories")) return route.fulfill({ json: { scope: url.includes("stories") ? `story:${novelId}` : "global", revision: 0, values: {} } });
    return route.fallback();
  });
  return { original, failNextVersion: () => { failVersion = true; }, progress: () => progress, saves: () => saves, annotations: () => annotations,
    savesForVersion: (version: string) => savedVersions.filter(saved => saved === version).length,
    delayedImage: () => {
      const src = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNQ6pgJAAITAUTGjr3DAAAAAElFTkSuQmCC";
      document = { ...document, content_version: "9".repeat(64), blocks: [
        { id: "delayed-art", kind: "p", text: "", html: `<p><img src="${src}" alt="Delayed dimension fixture"></p>` }, ...document.blocks,
      ] };
      progress = { chapter_number: 1, position: 1000, percent: 20, block_id: original.blocks[1].id,
        text_offset: 4000, text_quote: original.blocks[1].text.slice(4000, 4160), locator_content_version: document.content_version, revision: 1 };
    },
    illustrations: () => {
      const src = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNQ6pgJAAITAUTGjr3DAAAAAElFTkSuQmCC";
      document = { ...document, content_version: "c".repeat(64), blocks: [
        { id: "map", kind: "p", html: `<p>An illustrated opening. <img src="${src}" alt="Map of the island"></p>`, text: "An illustrated opening." },
        { id: "tower", kind: "p", html: `<p><img src="${src}" alt="The lighthouse"></p>`, text: "" },
        ...document.blocks,
      ] };
    },
    notes: () => {
      const texts = ["Note: " + "An author’s aside. ".repeat(100) + "Hidden search passage.", "The story begins here."];
      document = { ...document, source_format: "text", content_version: "e".repeat(64), plain_text: texts.join("\n\n"),
        blocks: texts.map((text, index) => ({ id: `note-fixture-${index}`, kind: "p", html: `<p>${text}</p>`, text })) };
    },
    richNotes: () => {
      const note = "A formatted aside. ".repeat(100) + "Hidden rich passage.";
      document = { ...document, source_format: "html", content_version: "d".repeat(64), plain_text: note + "\n\nThe story begins here.", blocks: [
        { id: "rich-note", kind: "p", text: note, html: `<p><em>A formatted aside.</em> ${"A formatted aside. ".repeat(99)}Hidden rich passage.</p>`, role: "author_note", role_provenance: "source" },
        { id: "rich-body", kind: "p", text: "The story begins here.", html: "<p>The story begins here.</p>" },
      ] };
    },
    revise: () => { archives.set(document.content_version, document); document = makeDocument("An inserted introduction changes this block's identifier. "); },
    replace: () => { archives.set(document.content_version, document); const blocks = document.blocks.map(block => ({ ...block, text: "Replacement passage.", html: "<p>Replacement passage.</p>", id: `new-${block.id}` })); document = { ...document, content_version: "f".repeat(64), blocks, plain_text: "Replacement passage." }; } };
}

async function glyph(page: Page, offset: number, blockId?: string) {
  return (blockId ? page.locator(`[data-block-id="${blockId}"]`) : page.locator(".reader-rich-block").nth(1)).evaluate((block, offset) => {
    const walker = document.createTreeWalker(block.querySelector("p")!, NodeFilter.SHOW_TEXT);
    let node: Text | null = null, remaining = offset;
    while (walker.nextNode()) {
      const candidate = walker.currentNode as Text;
      if (remaining < candidate.length) { node = candidate; break; }
      remaining -= candidate.length;
    }
    if (!node) throw new Error("Expected source character is unavailable");
    const range = document.createRange(); range.setStart(node, remaining); range.setEnd(node, remaining + 1);
    const rect = range.getBoundingClientRect();
    const container = block.closest(".reader__content")!.getBoundingClientRect();
    const header = document.querySelector(".reader__top")!.getBoundingClientRect();
    return { top: rect.top, left: rect.left, right: rect.right, viewportTop: Math.max(container.top, header.bottom),
      viewportBottom: container.bottom, viewportLeft: container.left, viewportRight: container.right };
  }, offset);
}

async function delayImage(page: Page) {
  await page.addInitScript(() => {
    const descriptor = Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, "complete")!;
    const state = window as unknown as { releaseFixtureImage?: boolean };
    Object.defineProperty(HTMLImageElement.prototype, "complete", { configurable: true, get() {
      if (this.alt === "Delayed dimension fixture" && !state.releaseFixtureImage) return false;
      return descriptor.get!.call(this);
    } });
    document.addEventListener("load", event => {
      if (event.target instanceof HTMLImageElement && event.target.alt === "Delayed dimension fixture" && !state.releaseFixtureImage) event.stopImmediatePropagation();
    }, true);
  });
}

test("initial position restoration waits for image dimensions", async ({ signedInPage: page }) => {
  const data = await fixture(page); data.delayedImage(); await delayImage(page);
  await page.goto(path);
  const reader = page.locator(".reader__content");
  await expect(reader).toHaveAttribute("aria-busy", "true");
  expect(data.saves()).toBe(0);
  await page.locator('img[alt="Delayed dimension fixture"]').evaluate(image => {
    (window as unknown as { releaseFixtureImage: boolean }).releaseFixtureImage = true;
    (image as HTMLElement).style.height = "450px";
    image.dispatchEvent(new Event("load"));
  });
  await expect(reader).toHaveAttribute("aria-busy", "false");
  const box = await glyph(page, 4000, data.original.blocks[1].id);
  expect(box.top).toBeGreaterThanOrEqual(box.viewportTop - 40);
  expect(box.top).toBeLessThan(box.viewportTop + 100);
});

for (const layout of ["scroll", "paged"] as const) test(`an image settling after the wait limit preserves the current ${layout} passage`, async ({ signedInPage: page }) => {
  const data = await fixture(page); data.delayedImage(); await delayImage(page);
  await page.evaluate(layout => localStorage.setItem("nexus-reader-layout", layout), layout);
  await page.goto(path);
  const reader = page.locator(".reader__content");
  await reader.evaluate(element => { element.style.overflowAnchor = "none"; });
  await expect(reader).toHaveAttribute("aria-busy", "false", { timeout: 8000 });
  // Navigate deliberately after the bounded wait, before the image settles.
  await page.keyboard.press("Control+f");
  await page.getByLabel("Find text", { exact: true }).fill("Sentence 200 follows");
  await page.getByLabel("Find text", { exact: true }).press("Enter");
  await expect.poll(() => page.evaluate(() => window.getSelection()?.toString())).toBe("Sentence 200 follows");
  await expect.poll(() => Number(data.progress()?.text_offset || 0)).toBeGreaterThan(10000);
  const offset = Number(data.progress()!.text_offset);
  await page.locator('img[alt="Delayed dimension fixture"]').evaluate(image => {
    (window as unknown as { releaseFixtureImage: boolean }).releaseFixtureImage = true;
    (image as HTMLElement).style.height = "450px";
    image.dispatchEvent(new Event("load"));
  });
  const box = await glyph(page, offset, data.original.blocks[1].id);
  if (layout === "scroll") {
    expect(box.top).toBeGreaterThanOrEqual(box.viewportTop - 40);
    expect(box.top).toBeLessThan(box.viewportTop + 100);
  } else {
    expect(box.right).toBeGreaterThan(box.viewportLeft); expect(box.left).toBeLessThan(box.viewportRight);
  }
  await expect(page).toHaveURL(new RegExp(`${path}$`));
});

test("illustrations zoom and navigate without moving the reading position", async ({ signedInPage: page }) => {
  const data = await fixture(page); data.illustrations();
  await page.goto(path);
  const reader = page.locator(".reader__content");
  await expect(reader).toHaveAttribute("aria-busy", "false");
  const image = page.getByRole("button", { name: "Open illustration: Map of the island" });
  await expect(image).toBeVisible();
  const before = await reader.evaluate(element => ({ top: element.scrollTop, left: element.scrollLeft }));
  await image.focus(); await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "Chapter illustration" });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Zoom in" }).click();
  await expect(dialog.getByRole("img", { name: "Map of the island" })).toHaveCSS("width", /px$/);
  await expect(dialog.getByText("150%", { exact: true })).toBeVisible();
  await page.keyboard.press("ArrowRight");
  await expect(dialog.getByRole("img", { name: "The lighthouse" })).toBeVisible();
  await expect(dialog.getByText("100%", { exact: true })).toBeVisible();
  const findings = await new AxeBuilder({ page }).include(".reader-image-dialog").analyze();
  expect(findings.violations.filter(item => ["serious", "critical"].includes(item.impact || ""))).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await expect(image).toBeFocused();
  expect(await reader.evaluate(element => ({ top: element.scrollTop, left: element.scrollLeft }))).toEqual(before);
  await expect(page).toHaveURL(new RegExp(`${path}$`));
});

test("long-paragraph offsets survive font changes, paging, reload, and revised source text", async ({ signedInPage: page }) => {
  const data = await fixture(page);
  await page.goto(path);
  await expect(page.getByRole("heading", { name: "Long paragraph", exact: true })).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  await page.locator(".reader-rich-block").nth(1).evaluate(block => {
    const node = block.querySelector("p")!.firstChild!;
    const range = document.createRange(); range.setStart(node, 4000); range.setEnd(node, 4001);
    const container = block.closest<HTMLElement>(".reader__content")!;
    container.scrollTop += range.getBoundingClientRect().top - container.getBoundingClientRect().top - 20;
  });
  await expect.poll(() => Number(data.progress()?.text_offset || 0)).toBeGreaterThan(3000);
  const offset = Number(data.progress()!.text_offset), quote = String(data.progress()!.text_quote);
  expect(quote.length).toBeGreaterThan(30);
  await page.keyboard.press("a");
  await expect(page.getByRole("dialog", { name: "Text settings" })).toBeVisible();
  await page.getByRole("button", { name: "Larger text" }).click();
  await page.getByRole("button", { name: "Larger text" }).click();
  await page.waitForTimeout(400);
  let box = await glyph(page, offset);
  expect(box.top).toBeGreaterThanOrEqual(box.viewportTop - 40);
  expect(box.top).toBeLessThan(box.viewportTop + 100);
  await page.getByRole("radio", { name: "Pages", exact: true }).click();
  await page.waitForTimeout(400);
  box = await glyph(page, offset);
  expect(box.right).toBeGreaterThan(box.viewportLeft);
  expect(box.left).toBeLessThan(box.viewportRight);
  await page.getByRole("radio", { name: "Scroll", exact: true }).click();
  await page.keyboard.press("Escape");
  await page.waitForTimeout(700);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Long paragraph", exact: true })).toBeAttached();
  await expect(page.locator(".reader__content")).toHaveAttribute("aria-busy", "false");
  await page.waitForTimeout(400);
  box = await glyph(page, Number(data.progress()!.text_offset));
  expect(box.top).toBeLessThan(box.viewportTop + 100);
  data.revise();
  await page.reload();
  await expect(page.locator(".reader__content")).toHaveAttribute("aria-busy", "false");
  await page.waitForTimeout(400);
  await expect(page.getByText(/saved passage is missing/)).toHaveCount(0);
  expect(await page.locator(".reader-rich-block").nth(1).textContent()).toContain(quote);
  data.replace();
  // An earlier rendition can still finish its debounce immediately before
  // reload. Check writes for the replacement itself, whose anchor needs review.
  const replacementVersion = "f".repeat(64);
  const before = data.savesForVersion(replacementVersion);
  await page.reload();
  await expect(page.getByText(/saved passage is missing/)).toBeVisible();
  await page.waitForTimeout(800);
  expect(data.savesForVersion(replacementVersion)).toBe(before);
  await page.getByRole("button", { name: "Keep this location" }).click();
  await expect(page.getByText(/saved passage is missing/)).toHaveCount(0);
  expect(data.savesForVersion(replacementVersion)).toBeGreaterThan(before);
});

test("a selected note keeps its character anchor after dialog focus and source revision", async ({ signedInPage: page }) => {
  const data = await fixture(page);
  await page.goto(path);
  await expect(page.getByRole("heading", { name: "Long paragraph", exact: true })).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  const selected = await page.locator(".reader-rich-block").nth(1).evaluate(block => {
    const text = block.querySelector("p")!.firstChild!;
    const range = document.createRange(); range.setStart(text, 8000); range.setEnd(text, 8035);
    const container = block.closest<HTMLElement>(".reader__content")!;
    container.scrollTop += range.getBoundingClientRect().top - container.getBoundingClientRect().top - 100;
    window.getSelection()!.removeAllRanges(); window.getSelection()!.addRange(range);
    return range.toString();
  });
  // Keyboard focus reveals the immersive toolbar without changing the passage.
  await page.getByRole("button", { name: "More reader actions" }).focus();
  await page.getByRole("button", { name: "More reader actions" }).click();
  await page.getByRole("menuitem", { name: "Add note" }).click();
  await page.getByRole("textbox", { name: "Note", exact: true }).fill("Remember this scene");
  await page.getByRole("button", { name: "Save note", exact: true }).click();
  await expect.poll(() => data.annotations().length).toBe(1);
  const note = data.annotations()[0];
  expect(note.text_offset).toBe(8000);
  expect(note.quote).toBe(selected);
  expect(String(note.text_quote)).toMatch(/^.{30}/);
  data.revise();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Long paragraph", exact: true })).toBeAttached();
  await page.getByRole("button", { name: "More reader actions" }).focus();
  await page.getByRole("button", { name: "More reader actions" }).click();
  await page.getByRole("menuitem", { name: /Bookmarks and notes/ }).click();
  await page.getByRole("button", { name: /Note: Remember this scene/ }).click();
  await expect(page.getByRole("dialog", { name: "Bookmarks and notes" })).toHaveCount(0);
  const inserted = "An inserted introduction changes this block's identifier. ".length;
  const box = await glyph(page, 8000 + inserted);
  expect(box.top).toBeGreaterThanOrEqual(box.viewportTop - 40);
  expect(box.top).toBeLessThan(box.viewportTop + 100);
});

test("a note opens its retained original without changing current reading progress", async ({ signedInPage: page }) => {
  const data = await fixture(page), paragraph = data.original.blocks[1];
  data.annotations().push({ id: 10, chapter_number: 1, annotation_type: "note", note: "Retained original scene", position: 4000, percent: 10,
    block_id: paragraph.id, text_offset: 8000, text_quote: paragraph.text.slice(8000, 8160),
    quote_prefix: paragraph.text.slice(7936, 8000), quote_suffix: paragraph.text.slice(8160, 8224),
    locator_content_version: data.original.content_version, locator_variant: "original" });
  data.replace();
  await page.goto(path);
  await expect(page.getByText("Replacement passage.").first()).toBeVisible();
  await page.waitForTimeout(700);
  const before = data.saves();
  await page.getByRole("button", { name: "More reader actions" }).focus();
  await page.getByRole("button", { name: "More reader actions" }).click();
  await page.getByRole("menuitem", { name: /Bookmarks and notes/ }).click();
  data.failNextVersion();
  await page.getByRole("button", { name: "Saved text", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Chapter versions" })).toBeVisible();
  await expect(page.getByText("Couldn’t load this original. Connect to Nexus and try again.")).toBeVisible();
  await page.getByRole("button", { name: "Retry original", exact: true }).click();
  const region = page.getByRole("region", { name: "Saved original text" });
  await expect(region).toContainText("Sentence 0 follows");
  await expect.poll(() => region.evaluate(element => element.scrollTop)).toBeGreaterThan(1000);
  await expect(page.getByText(/saved quote could not be located/)).toHaveCount(0);
  const accessibility = await new AxeBuilder({ page }).include('[role="dialog"]').withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  expect(accessibility.violations.filter(value => value.impact === "serious" || value.impact === "critical")).toEqual([]);
  await region.press("PageDown");
  await page.waitForTimeout(700);
  expect(data.saves()).toBe(before);
  await page.getByRole("button", { name: "Close chapter versions", exact: true }).click();
  await expect(page.getByText("Replacement passage.").first()).toBeVisible();
});

test("chapter search jumps to a long-paragraph match with keyboard and paged navigation", async ({ signedInPage: page }) => {
  await fixture(page);
  await page.goto(path);
  await expect(page.getByRole("heading", { name: "Long paragraph", exact: true })).toBeVisible();
  await page.keyboard.press("Control+f");
  await expect(page.getByRole("dialog", { name: "Search this chapter" })).toBeVisible();
  await page.getByLabel("Find text", { exact: true }).fill("Sentence 1000 follows");
  await expect(page.getByRole("status").filter({ hasText: "1 match." })).toBeVisible();
  const audit = await new AxeBuilder({ page }).include('[role="dialog"]').withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  expect(audit.violations.filter(row => row.impact === "serious" || row.impact === "critical")).toEqual([]);
  await page.getByLabel("Find text", { exact: true }).press("Enter");
  await expect(page.getByRole("dialog", { name: "Search this chapter" })).toHaveCount(0);
  const offset = longParagraph.indexOf("Sentence 1000 follows");
  let box = await glyph(page, offset);
  expect(box.top).toBeGreaterThanOrEqual(box.viewportTop - 40);
  expect(box.top).toBeLessThan(box.viewportTop + 100);
  await page.keyboard.press("a");
  await page.getByRole("radio", { name: "Pages", exact: true }).click();
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "More reader actions" }).focus();
  await page.getByRole("button", { name: "More reader actions" }).click();
  await page.getByRole("menuitem", { name: /Search this chapter/ }).click();
  await page.getByLabel("Find text", { exact: true }).fill("Sentence 1300 follows");
  await page.getByLabel("Find text", { exact: true }).press("Enter");
  box = await glyph(page, longParagraph.indexOf("Sentence 1300 follows"));
  expect(box.right).toBeGreaterThan(box.viewportLeft);
  expect(box.left).toBeLessThan(box.viewportRight);
});

test("search can reveal a collapsed author note without changing the saved note preference", async ({ signedInPage: page }) => {
  const data = await fixture(page); data.notes();
  await page.goto(path);
  await expect(page.getByRole("heading", { name: "Long paragraph", exact: true })).toBeVisible();
  await page.keyboard.press("a");
  await page.getByRole("radio", { name: "Collapse", exact: true }).click();
  await page.keyboard.press("Escape");
  await page.keyboard.press("Control+f");
  await page.getByLabel("Find text", { exact: true }).fill("Hidden search passage");
  await page.getByLabel("Find text", { exact: true }).press("Enter");
  await expect(page.getByRole("button", { name: "Show less", exact: true })).toBeVisible();
  await expect.poll(() => page.evaluate(() => window.getSelection()?.toString())).toBe("Hidden search passage");
  await page.keyboard.press("a");
  await expect(page.getByRole("radio", { name: "Collapse", exact: true })).toBeChecked();
});

test("rich source notes retain emphasis, support hide/show, and restore searched passages", async ({ signedInPage: page }) => {
  const data = await fixture(page); data.richNotes();
  await page.goto(path);
  await expect(page.getByRole("heading", { name: "Long paragraph", exact: true })).toBeVisible();
  await expect(page.locator('[data-block-id="rich-note"] em')).toHaveText("A formatted aside.");
  await page.keyboard.press("a");
  await page.getByRole("radio", { name: "Hide", exact: true }).click();
  await expect(page.locator('[data-block-id="rich-note"]')).toHaveCount(0);
  await expect(page.locator('[data-block-id="rich-body"]')).toContainText("The story begins here.");
  await page.getByRole("radio", { name: "Collapse", exact: true }).click();
  await page.keyboard.press("Escape");
  await page.keyboard.press("Control+f");
  await page.getByLabel("Find text", { exact: true }).fill("Hidden rich passage");
  await page.getByLabel("Find text", { exact: true }).press("Enter");
  await expect.poll(() => page.evaluate(() => window.getSelection()?.toString())).toBe("Hidden rich passage");
  await expect(page.getByRole("button", { name: "Show less", exact: true })).toBeVisible();
});
