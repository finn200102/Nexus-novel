import { createHash } from "node:crypto";
import type { Page } from "@playwright/test";
import { test, expect } from "./fixtures";
import type { ChapterDocument } from "../src/components/reader/chapterDocument";
import type { AudioManifest } from "../src/services/audioAlignment";

const novelId = 94, chapterId = 9401, jobId = 940;
const readerPath = `/library/1/novels/${novelId}/1`;
const blocks = ["opening", "harbour", "lighthouse"].map((name, index) => {
  const text = `${name[0].toUpperCase()}${name.slice(1)} passage. ` +
    `The keeper recorded this part of the journey carefully. `.repeat(35);
  const html = `<p>${text}</p>`;
  return { id: `b-${createHash("sha256").update(html).digest("hex").slice(0, 24)}-${index}`, kind: "p", text, html };
});
const document: ChapterDocument = {
  schema_version: 1, source_format: "html", blocks,
  content_version: createHash("sha256").update(blocks.map(block => block.html).join("")).digest("hex"),
  plain_text: blocks.map(block => block.text).join("\n\n"),
};
const manifest: AudioManifest = {
  job_id: jobId, source_version: document.content_version, current_source: true,
  rendition: "original", include_author_notes: false, precision: "segment", duration_seconds: 32,
  segments: [
    { part_index: 0, block_id: null, text_offset: null, text_length: null, start_seconds: 0, end_seconds: 2 },
    ...blocks.map((block, index) => ({ part_index: index + 1, block_id: block.id,
      text_offset: 0, text_length: block.text.length, start_seconds: 2 + index * 10, end_seconds: 12 + index * 10 })),
  ],
};
function wave(seconds: number) {
  const frames = seconds * 24000, body = Buffer.alloc(44 + frames * 2);
  body.write("RIFF"); body.writeUInt32LE(body.length - 8, 4); body.write("WAVEfmt ", 8);
  body.writeUInt32LE(16, 16); body.writeUInt16LE(1, 20); body.writeUInt16LE(1, 22);
  body.writeUInt32LE(24000, 24); body.writeUInt32LE(48000, 28);
  body.writeUInt16LE(2, 32); body.writeUInt16LE(16, 34); body.write("data", 36); body.writeUInt32LE(frames * 2, 40);
  return body;
}
type NativeAudioWindow = Window & { fixtureAudio?: HTMLAudioElement };
async function setup(page: Page, outdated = false) {
  const saves: Record<string, unknown>[] = [];
  let progress: Record<string, unknown> | null = null;
  let generated = 0;
  await page.addInitScript(() => {
    // Observe the real browser element; decoding, playback and media events stay native.
    const AudioConstructor = window.Audio;
    window.Audio = new Proxy(AudioConstructor, {
      construct(target, args) {
        const audio = Reflect.construct(target, args) as HTMLAudioElement;
        (window as NativeAudioWindow).fixtureAudio = audio;
        return audio;
      },
    });
  });
  await page.route(/127\.0\.0\.1:8000|localhost:8000|\/api\//, async route => {
    const url = new URL(route.request().url()).pathname.replace(/^\/api(?=\/)/, "");
    if (url === `/novel/${novelId}`) return route.fulfill({ json: { id: novelId, library_id: 1, title: "Measured narration", author: "Fixture", total_chapters: 1 } });
    if (url === `/chapter/${novelId}`) return route.fulfill({ json: [{ id: chapterId, chapter_number: 1, title: "Across the harbour", content_status: "PRESENT" }] });
    if (url === `/chapter/content/library/1/${novelId}/1`) return route.fulfill({ json: { id: chapterId, novel_id: novelId, chapter_number: 1, title: "Across the harbour", document, content: document.plain_text } });
    if (url === `/chapter/progress/${novelId}`) {
      if (route.request().method() === "PUT") {
        const body = route.request().postDataJSON(); saves.push(body);
        progress = { ...body, novel_id: novelId, revision: saves.length, locator_content_version: body.content_version, updated_at: new Date().toISOString() };
      }
      return route.fulfill({ json: progress });
    }
    if (url === `/chapter/annotations/${novelId}`) return route.fulfill({ json: [] });
    if (url === "/reader/preferences" || url.startsWith("/reader/preferences/stories")) return route.fulfill({ json: { scope: url.includes("stories") ? `story:${novelId}` : "global", revision: 0, values: {} } });
    if (url === "/audio/jobs") {
      if (route.request().method() === "POST") { generated++; return route.fulfill({ status: 500, json: { detail: "No generation in playback tests" } }); }
      return route.fulfill({ json: [{ id: jobId, status: "completed", provider_id: "custom", provider_model: "fixture", provider_voice: "fixture", total_parts: 4, completed_parts: 4, audio_ready: true }] });
    }
    if (url === `/audio/jobs/${jobId}/manifest`) return route.fulfill({ json: outdated ? { ...manifest, source_version: "a".repeat(64), current_source: false } : manifest });
    if (url === `/audio/jobs/${jobId}/audio`) return route.fulfill({ contentType: "audio/wav", body: wave(32) });
    return route.fallback();
  });
  await page.evaluate(() => {
    const prefix = `nexus-account:${encodeURIComponent(location.origin)}:7:`;
    localStorage.setItem(prefix + "nexus-reader-tts-engine", "openai_compatible");
    localStorage.setItem(prefix + "nexus-reader-tts-execution", "server");
  });
  await page.goto(readerPath);
  await expect(page.locator(".reader__content")).toHaveAttribute("aria-busy", "false", { timeout: 10_000 });
  await page.getByRole("button", { name: "Listen", exact: true }).click();
  await expect(page.getByRole("button", { name: "Play", exact: true })).toBeVisible();
  // Opening Listen preserves the original viewport through fonts and its
  // bounded 250 ms layout restoration. Complete that transition before the
  // fixture positions a different passage programmatically.
  await page.evaluate(async () => { await document.fonts.ready; });
  await page.waitForTimeout(300);
  return { saves, generated: () => generated };
}
async function showBlock(page: Page, index: number) {
  await page.locator(`[data-block-id="${blocks[index].id}"]`).evaluate(element => {
    const reader = element.closest<HTMLElement>(".reader__content")!;
    const top = Math.max(reader.getBoundingClientRect().top, document.querySelector(".reader__top")!.getBoundingClientRect().bottom);
    reader.scrollTop += element.getBoundingClientRect().top - top - 10;
  });
  await expect.poll(async () => page.locator(`[data-block-id="${blocks[index].id}"]`).evaluate(element => {
    const reader = element.closest<HTMLElement>(".reader__content")!;
    const viewportTop = Math.max(reader.getBoundingClientRect().top, document.querySelector(".reader__top")!.getBoundingClientRect().bottom);
    const top = element.getBoundingClientRect().top;
    return top >= viewportTop - 2 && top <= viewportTop + 30;
  })).toBe(true);
}
async function audioState(page: Page) {
  return page.evaluate(() => {
    const audio = (window as NativeAudioWindow).fixtureAudio;
    return audio ? { paused: audio.paused, time: audio.currentTime, duration: audio.duration, ready: audio.readyState } : null;
  });
}

test("visible text starts at its measured audio boundary and audio returns to its stable passage", async ({ signedInPage: page }) => {
  const data = await setup(page);
  await showBlock(page, 1);
  await page.getByRole("button", { name: "Listen from this passage", exact: true }).click();
  await expect(page.getByRole("button", { name: "Pause", exact: true })).toBeVisible();
  await expect.poll(async () => (await audioState(page))?.duration).toBe(32);
  const started = await audioState(page);
  expect(started?.time).toBeGreaterThanOrEqual(12);
  expect(started?.time).toBeLessThan(15);
  await expect.poll(() => data.saves.some(save => save.block_id === blocks[1].id && save.content_version === document.content_version)).toBe(true);
  // Native seeking and timeupdate must cross into the third measured segment.
  await page.getByRole("button", { name: "Forward 15 seconds", exact: true }).click();
  await expect.poll(() => data.saves.some(save => save.block_id === blocks[2].id && save.text_offset === 0)).toBe(true);
  await page.getByRole("button", { name: "Read this passage", exact: true }).click();
  await expect(page.getByRole("button", { name: "Play", exact: true })).toBeVisible();
  expect((await audioState(page))?.paused).toBe(true);
  const geometry = await page.locator(`[data-block-id="${blocks[2].id}"]`).evaluate(element => {
    const reader = element.closest(".reader__content")!.getBoundingClientRect();
    const heading = document.querySelector(".reader__top")!.getBoundingClientRect();
    return { top: element.getBoundingClientRect().top, viewportTop: Math.max(reader.top, heading.bottom) };
  });
  expect(geometry.top).toBeGreaterThanOrEqual(geometry.viewportTop - 40);
  expect(geometry.top).toBeLessThan(geometry.viewportTop + 100);
  for (const save of data.saves.filter(save => save.block_id)) {
    expect(save.content_version).toBe(document.content_version);
    expect(blocks.map(block => block.id)).toContain(save.block_id);
  }
  expect(data.generated()).toBe(0);
});

test("an earlier recording stays playable without passage links or reading writes", async ({ signedInPage: page }) => {
  const data = await setup(page, true);
  await page.getByRole("button", { name: "Listen from this passage", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "cannot be linked" })).toBeVisible();
  await expect(page.getByText(/earlier chapter version/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Read this passage", exact: true })).toHaveCount(0);
  // Let any pre-play reader debounce settle, then assert native playback makes no new writes.
  await page.waitForTimeout(800);
  const before = data.saves.length;
  await page.getByRole("button", { name: "Play", exact: true }).click();
  await expect.poll(async () => (await audioState(page))?.paused).toBe(false);
  await page.getByRole("button", { name: "Forward 15 seconds", exact: true }).click();
  await expect.poll(async () => (await audioState(page))?.time || 0).toBeGreaterThanOrEqual(15);
  await page.waitForTimeout(900);
  expect(data.saves.length).toBe(before);
  await page.getByRole("button", { name: "Pause", exact: true }).click();
  expect(data.generated()).toBe(0);
});
