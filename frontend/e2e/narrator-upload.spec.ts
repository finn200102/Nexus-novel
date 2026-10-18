import type { Page } from "@playwright/test";
import { test, expect } from "./fixtures";

function recording(seconds: number): Buffer {
  const frames = seconds * 24000, wav = Buffer.alloc(44 + frames * 2);
  wav.write("RIFF"); wav.writeUInt32LE(wav.length - 8, 4); wav.write("WAVEfmt ", 8);
  wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22);
  wav.writeUInt32LE(24000, 24); wav.writeUInt32LE(48000, 28);
  wav.writeUInt16LE(2, 32); wav.writeUInt16LE(16, 34); wav.write("data", 36);
  wav.writeUInt32LE(frames * 2, 40);
  return wav;
}

type UploadReceipt = {
  name: unknown; language: unknown; transcript: unknown;
  start: unknown; duration: unknown; decodedBytes: number;
};
async function narratorApi(page: Page, rejectUpload = false) {
  const uploads: UploadReceipt[] = [];
  await page.route(/127\.0\.0\.1:8000|localhost:8000|\/api\//, async route => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api(?=\/)/, "");
    if (path === "/audio/voices/capabilities") return route.fulfill({ json: { configured: true, languages: ["English", "German"] } });
    if (path === "/audio/voices/default") return route.fulfill({ json: { voice_profile_id: null, revision: 0 } });
    if (path === "/audio/voices") {
      if (route.request().method() !== "POST") return route.fulfill({ json: [] });
      const body = route.request().postDataJSON();
      // Keep only bounded metadata in test evidence; never output the recording.
      uploads.push({ name: body.name, language: body.language, transcript: body.transcript,
        start: body.excerpt_start_seconds, duration: body.excerpt_duration_seconds,
        decodedBytes: typeof body.audio_base64 === "string" ? Buffer.from(body.audio_base64, "base64").byteLength : 0 });
      if (rejectUpload) return route.fulfill({ status: 413, contentType: "text/html", body: "<html><body>413 Request Entity Too Large</body></html>" });
      return route.fulfill({ status: 202, json: { id: 314, name: body.name, language: body.language, transcript: body.transcript, status: "queued", error: null, preview_ready: false } });
    }
    return route.fallback();
  });
  await page.goto("/settings/voices");
  await expect(page.getByLabel(/^Voice recording/)).toBeVisible();
  return uploads;
}

test("native narrator upload selects a bounded excerpt from a recording larger than one megabyte", async ({ signedInPage: page }) => {
  const uploads = await narratorApi(page);
  const wav = recording(60);
  expect(wav.byteLength).toBeGreaterThan(1024 * 1024);
  await page.getByLabel(/^Narrator name/).fill("Native narrator");
  await page.getByLabel(/^Voice recording/).setInputFiles({ name: "sixty-second-reference.wav", mimeType: "audio/wav", buffer: wav });
  // Actual browser media metadata drives selection; no Audio constructor or
  // duration/event overrides are used in this regression.
  const preview = page.getByLabel("Selected recording preview", { exact: true });
  await expect.poll(() => preview.evaluate(audio => (audio as HTMLAudioElement).duration)).toBe(60);
  await expect(page.getByLabel("Excerpt start (seconds)", { exact: true })).toHaveValue("0");
  await expect(page.getByLabel("Excerpt end (seconds)", { exact: true })).toHaveValue("15");
  await page.getByLabel("Selected excerpt transcript (optional)", { exact: true }).fill("Words from an earlier selection.");
  await page.getByLabel("Excerpt start (seconds)", { exact: true }).fill("5");
  await page.getByLabel("Excerpt end (seconds)", { exact: true }).fill("20");
  await expect(page.getByLabel("Selected excerpt transcript (optional)", { exact: true })).toHaveValue("");
  await expect(page.getByRole("status").filter({ hasText: "The excerpt changed." })).toBeVisible();
  await page.getByLabel("Selected excerpt transcript (optional)", { exact: true }).fill("Only the chosen passage.");
  expect(uploads).toHaveLength(0);
  await page.getByRole("button", { name: "Create narrator voice", exact: true }).click();
  await expect.poll(() => uploads.length).toBe(1);
  expect(uploads[0]).toEqual({ name: "Native narrator", language: "English", transcript: "Only the chosen passage.", start: 5, duration: 15, decodedBytes: wav.byteLength });
  await expect(page.getByText("Preparing locally…", { exact: false })).toBeVisible();
});

test("native narrator upload explains a 413 rejection and preserves the selected file", async ({ signedInPage: page }) => {
  const uploads = await narratorApi(page, true);
  const wav = recording(8);
  await page.getByLabel(/^Narrator name/).fill("Retry narrator");
  const file = page.getByLabel(/^Voice recording/);
  await file.setInputFiles({ name: "retry-reference.wav", mimeType: "audio/wav", buffer: wav });
  await expect.poll(() => page.getByLabel("Selected recording preview", { exact: true }).evaluate(audio => (audio as HTMLAudioElement).duration)).toBe(8);
  await page.getByRole("button", { name: "Create narrator voice", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("server’s narrator upload limit needs to be increased");
  await expect(page.getByLabel(/^Narrator name/)).toHaveValue("Retry narrator");
  expect(await file.evaluate(input => ({ count: (input as HTMLInputElement).files?.length, name: (input as HTMLInputElement).files?.[0]?.name }))).toEqual({ count: 1, name: "retry-reference.wav" });
  expect(uploads).toHaveLength(1);
  expect(uploads[0]).toEqual({ name: "Retry narrator", language: "English", transcript: "", start: undefined, duration: undefined, decodedBytes: wav.byteLength });
  await expect(page.getByRole("button", { name: "Create narrator voice", exact: true })).toBeEnabled();
});
