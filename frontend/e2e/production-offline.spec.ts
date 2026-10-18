import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test("cross-tab logout closes a private illustration viewer", async ({ page, context }, testInfo) => {
  test.skip(testInfo.config.metadata.productionOffline !== true, "Requires the production offline fixture server");
  await context.request.post("/__test/online");
  await page.goto("/login");
  await page.getByLabel(/username/i).fill("reader-a");
  await page.getByLabel(/password/i).fill("fixture-password");
  await page.getByRole("button", { name: /login|sign in/i }).click();
  await expect(page).not.toHaveURL(/login/);
  await page.goto("/library/1/novels/42/8");
  await page.getByRole("button", { name: "Open illustration: Offline island map" }).click();
  await expect(page.getByRole("dialog", { name: "Chapter illustration" })).toBeVisible();
  const other = await context.newPage();
  other.on("dialog", dialog => void dialog.accept());
  await other.goto("/more");
  await other.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page).toHaveURL(/login/);
  await expect(page.getByRole("dialog", { name: "Chapter illustration" })).toHaveCount(0);
  await expect(page.getByRole("img", { name: "Offline island map" })).toHaveCount(0);
});

test("production shell and account-scoped text survive offline reload", async ({ page, context, browserName }, testInfo) => {
  test.skip(testInfo.config.metadata.productionOffline !== true, "Requires the production offline fixture server");
  await context.request.post("/__test/online");
  await page.goto("/login");
  await page.getByLabel(/username/i).fill("reader-a");
  await page.getByLabel(/password/i).fill("fixture-password");
  await page.getByRole("button", { name: /login|sign in/i }).click();
  await expect(page).not.toHaveURL(/login/);
  await page.goto("/library/1/novels/42");
  await page.getByRole("tab", { name: "Chapters" }).click();
  await page.getByRole("button", { name: "Save next 10 offline" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Saved 10 chapters offline." })).toBeVisible();
  await page.evaluate(async () => { await navigator.serviceWorker.ready; });
  await expect.poll(() => page.evaluate(() => !!navigator.serviceWorker.controller)).toBe(true);
  await page.goto("/library/1/novels/42/1");
  await expect(page.getByText("Offline fixture text for chapter 1.")).toBeVisible();
  // Playwright's WebKit network-offline emulation errors before navigation
  // reaches the service worker. Exercise real HTTP connection loss there;
  // Safari hardware/radio-offline qualification remains a separate gate.
  if ((browserName === "webkit" || browserName === "firefox")) await context.request.post("/__test/offline");
  else await context.setOffline(true);
  try {
    await page.goto("/library/1/novels/42/7");
    await expect(page.getByText("Offline fixture text for chapter 7.")).toBeVisible();
    await page.reload();
    await expect(page.getByText("Offline fixture text for chapter 7.")).toBeVisible();
    await expect(page.getByText("Offline mode: showing the last cached copy.")).toBeVisible();
    await page.keyboard.press("Control+f");
    await page.getByLabel("Find text", { exact: true }).fill("fixture text");
    await expect(page.getByRole("status").filter({ hasText: "1 match." })).toBeVisible();
    await page.getByLabel("Find text", { exact: true }).press("Enter");
    await expect.poll(() => page.evaluate(() => window.getSelection()?.toString())).toBe("fixture text");
    await page.goto("/library/1/novels/42/8");
    await expect(page.getByText("Offline fixture text for chapter 8.")).toBeVisible();
    await page.reload();
    await page.getByRole("button", { name: "Open illustration: Offline island map" }).click();
    const illustration = page.getByRole("dialog", { name: "Chapter illustration" });
    await expect(illustration).toBeVisible();
    await expect.poll(() => illustration.getByRole("img").evaluate(image => (image as HTMLImageElement).naturalWidth)).toBe(1);
    await illustration.getByRole("button", { name: "Zoom in" }).click();
    await expect(illustration.getByText("150%", { exact: true })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(illustration).not.toBeVisible();
  } finally {
    await context.setOffline(false);
    await context.request.post("/__test/online");
  }
});

test("signing out in another tab removes the visible private reader", async ({ page, context }, testInfo) => {
  test.skip(testInfo.config.metadata.productionOffline !== true, "Requires the production offline fixture server");
  await context.request.post("/__test/online");
  await page.goto("/login");
  await page.getByLabel(/username/i).fill("reader-a");
  await page.getByLabel(/password/i).fill("fixture-password");
  await page.getByRole("button", { name: /login|sign in/i }).click();
  await expect(page).not.toHaveURL(/login/);
  await page.goto("/library/1/novels/42/1");
  await expect(page.getByText("Offline fixture text for chapter 1.")).toBeVisible();
  const otherTab = await context.newPage();
  await page.keyboard.press("Control+f");
  await page.getByLabel("Find text", { exact: true }).fill("fixture text");
  await expect(page.getByRole("status").filter({ hasText: "1 match." })).toBeVisible();
  otherTab.on("dialog", (dialog) => void dialog.accept());
  await otherTab.goto("/more");
  await otherTab.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page).toHaveURL(/login/);
  await expect(page.getByText("Offline fixture text for chapter 1.")).not.toBeVisible();
  await expect(page.getByRole("dialog", { name: "Search this chapter" })).toHaveCount(0);
});

test("switching accounts cannot revive another reader's offline chapter", async ({ page, context, browserName }, testInfo) => {
  test.skip(testInfo.config.metadata.productionOffline !== true, "Requires the production offline fixture server");
  await context.request.post("/__test/online");
  page.on("dialog", (dialog) => void dialog.accept());
  await page.goto("/login");
  await page.getByLabel(/username/i).fill("reader-a");
  await page.getByLabel(/password/i).fill("fixture-password");
  await page.getByRole("button", { name: /login|sign in/i }).click();
  await expect(page).not.toHaveURL(/login/);
  await page.goto("/library/1/novels/42/1");
  await expect(page.getByText("Offline fixture text for chapter 1.")).toBeVisible();
  await page.goto("/more");
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page).toHaveURL(/login/);
  await page.getByLabel(/username/i).fill("reader-b");
  await page.getByLabel(/password/i).fill("fixture-password");
  await page.getByRole("button", { name: /login|sign in/i }).click();
  await expect(page).not.toHaveURL(/login/);
  if ((browserName === "webkit" || browserName === "firefox")) await context.request.post("/__test/offline");
  else await context.setOffline(true);
  try {
    await page.goto("/library/1/novels/42/1");
    await expect(page.getByText("Couldn’t load this chapter. Check your connection and try again.")).toBeVisible();
    await expect(page.getByText("Offline fixture text for chapter 1.")).not.toBeVisible();
  } finally {
    await context.setOffline(false);
    await context.request.post("/__test/online");
  }
});

test("a delayed offline batch cannot write the previous reader's content into the next account", async ({ page, context }, testInfo) => {
  test.skip(testInfo.config.metadata.productionOffline !== true, "Requires the production offline fixture server");
  await context.request.post("/__test/online");
  await page.goto("/login");
  await page.getByLabel(/username/i).fill("reader-a");
  await page.getByLabel(/password/i).fill("fixture-password");
  await page.getByRole("button", { name: /login|sign in/i }).click();
  await expect(page).not.toHaveURL(/login/);
  await page.goto("/library/1/novels/42");
  await page.getByRole("tab", { name: "Chapters" }).click();
  await context.request.post("/__test/hold-chapter?number=1");
  try {
    await page.getByRole("button", { name: "Save next 10 offline" }).click();
    await expect.poll(async () => (await (await context.request.get("/__test/held-chapter-status")).json()).requested).toBe(true);
    const nextReader = await context.newPage();
    nextReader.on("dialog", dialog => void dialog.accept());
    await nextReader.goto("/more");
    await nextReader.getByRole("button", { name: "Sign out", exact: true }).click();
    await expect(nextReader).toHaveURL(/login/);
    await nextReader.getByLabel(/username/i).fill("reader-b");
    await nextReader.getByLabel(/password/i).fill("fixture-password");
    await nextReader.getByRole("button", { name: /login|sign in/i }).click();
    await expect(nextReader).not.toHaveURL(/login/);
    await context.request.post("/__test/release-chapter");
    await page.goto("/offline");
    await expect(page.getByRole("heading", { name: "Offline library", exact: true })).toBeVisible();
    await expect(page.getByText("Offline fixture text for chapter 1.")).toHaveCount(0);
    const counts = await page.evaluate(async () => {
      const suffix = ":6d62702d-e9e2-4a6d-97ee-9b2812a61d83:reader-db";
      const databases = typeof indexedDB.databases === "function" ? await indexedDB.databases() : [];
      const name = databases.find(database => database.name?.endsWith(suffix))?.name ?? `nexus-account:${encodeURIComponent(location.origin)}${suffix}`;
      const db = await new Promise<IDBDatabase>((resolve, reject) => {
        const request = indexedDB.open(name);
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      });
      try {
        const stores = ["chapters", "translations", "chapter_audio", "chapter_audio_jobs", "chapter_audio_segments"].filter(store => db.objectStoreNames.contains(store));
        if (!stores.length) return [];
        const transaction = db.transaction(stores, "readonly");
        return await Promise.all(stores.map(store => new Promise<number>((resolve, reject) => {
          const request = transaction.objectStore(store).count();
          request.onsuccess = () => resolve(request.result);
          request.onerror = () => reject(request.error);
        })));
      } finally { db.close(); }
    });
    expect(counts.length).toBeGreaterThanOrEqual(4);
    expect(counts.every(count => count === 0)).toBe(true);
  } finally {
    await context.request.post("/__test/release-chapter");
    await context.request.post("/__test/online");
  }
});

test("production inventory preserves UUID-bound private media bytes and protects live audio and pending progress", async ({ page, context, browserName }, testInfo) => {
  test.skip(testInfo.config.metadata.productionOffline !== true, "Requires the production offline fixture server");
  await context.request.post("/__test/online");
  await page.goto("/login");
  const serverDeletes: string[] = [];
  page.on("request", request => { if (request.method() === "DELETE" && request.url().includes("/api/")) serverDeletes.push(request.url()); });
  const seeded = await page.evaluate(async browserName => {
    const name = `nexus-account:${encodeURIComponent(location.origin)}:a42a4617-a64b-440e-83bf-e52f340409f0:reader-db`;
    const audio = await (await fetch("/api/audio/jobs/808/audio", { headers: { Authorization: "Bearer fixture-7" } })).arrayBuffer();
    const identity={chapter_key:"22222222-2222-4222-8222-0000000186a8",manifest_epoch:"11111111-1111-4111-8111-111111111111",manifest_revision:"1"};
    const version = "8".repeat(64), text = "Private upgraded offline chapter.";
    const document = { schema_version: 1, content_version: version, source_format: "html", plain_text: text,
      blocks: [{ id: "legacy-anchor", kind: "p", text, html: `<p>${text}<img src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNQ6pgJAAITAUTGjr3DAAAAAElFTkSuQmCC" alt="Saved"><img src="https://unavailable.invalid/remote.png" alt="Missing"></p>` }] };
    const records: { store: string; row: Record<string, unknown> }[] = [
      { store: "chapters", row: { cache_key: "42:8", id: 1008, novel_id: 42, chapter_number: 8, title: "Upgraded chapter", content: text,
        library_id: 1, novel_title: "Private upgraded story", pinned: true, cached_at: 1000, document } },
      { store: "chapter_audio", row: { cache_key: "42:8", audio_data: audio, audio_type: "audio/wav", created_at: 1000,
        manifest: { job_id: 808, source_version: version, rendition: "original", precision: "unavailable", duration_seconds: null, segments: [], include_author_notes: false } } },
      { store: "chapter_audio_jobs", row: { cache_key: "42:8", novelId: 42, chapterNumber: 8, status: "failed", source_version: version, completed_chunks: 1, total_chunks: 2 } },
      { store: "chapter_audio_segments", row: { segment_key: "42:8:0", cache_key: "42:8", index: 0,
        // Safari cannot create legacy Blob IDB records; its supported byte codec
        // is qualified here while Chromium/Firefox also exercise old Blob rows.
        ...((browserName === "webkit" || browserName === "firefox") ? { audio_data: audio, audio_type: "audio/wav" } : { audio: new Blob([audio], { type: "audio/wav" }) }) } },
      ...[1808, 1809].map(id => ({ store: "translations", row: { cache_key: `42:8:${id}`, id, novel_id: 42, chapter_number: 8,
        source_version: id === 1808 ? version : "9".repeat(64), status: "completed", completed_blocks: 1, total_blocks: 1,
        language: id === 1808 ? "de" : "ja", document: { ...document, blocks: [{ id: "legacy-anchor", kind: "p", text: "Private translated text", html: "<p>Private translated text</p>" }] } } })),
    ];
    for(const record of records){Object.assign(record.row,identity,{novel_id:42,chapter_number:8});for(const field of ["cache_key","segment_key"]){if(typeof record.row[field]==="string")record.row[field]=(record.row[field] as string).replace("42:8",`42:${identity.chapter_key}`);}if(record.row.manifest)Object.assign(record.row.manifest as object,identity);}
    const db = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open(name, 6);
      request.onupgradeneeded = () => {
        request.result.createObjectStore("offline_metadata",{keyPath:"key"});
        const chapters = request.result.createObjectStore("chapters", { keyPath: "cache_key" });
        chapters.createIndex("cached_at", "cached_at"); chapters.createIndex("novel_id", "novel_id");
        for (const store of ["chapter_audio", "chapter_audio_jobs", "translations"]) request.result.createObjectStore(store, { keyPath: "cache_key" });
        const segments = request.result.createObjectStore("chapter_audio_segments", { keyPath: "segment_key" }); segments.createIndex("cache_key", "cache_key");
      };
      request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
    });
    try { await new Promise<void>((resolve, reject) => {
      const tx = db.transaction([...db.objectStoreNames], "readwrite");
      for (const record of records) tx.objectStore(record.store).put(record.row);
      const metadata=tx.objectStore("offline_metadata");metadata.put({key:"chapter-manifest:42",...identity,retired_epochs:[]});metadata.put({key:"chapter-address:42:8",...identity});metadata.put({key:`chapter-key:42:${identity.chapter_key}`,...identity,chapter_number:8});
      tx.objectStore("chapter_audio_jobs").put({ cache_key: `lease:42:${identity.chapter_key}`,...identity, novelId: 42, chapterNumber: 8,
        databaseName: name, owner: "native-fixture-owner", token: "native-fixture-token", expiresAt: Date.now() + 3_600_000 });
      tx.oncomplete = () => resolve(); tx.onerror = () => reject(tx.error); tx.onabort = () => reject(tx.error);
    }); } finally { db.close(); }
    const expectedBytes = records.reduce((sum, record) => {
      const value = { ...record.row }; let bytes = 0;
      for (const key of ["audio", "audio_data"]) {
        const blob = value[key];
        if (blob instanceof Blob) { bytes += blob.size; delete value[key]; }
        else if (blob instanceof ArrayBuffer) { bytes += blob.byteLength; delete value[key]; }
      }
      return sum + bytes + new TextEncoder().encode(JSON.stringify(value)).length;
    }, 0);
    const translationBytes = records.filter(record => record.store === "translations").reduce((sum, record) => sum + new TextEncoder().encode(JSON.stringify(record.row)).length, 0);
    return { name, expectedBytes, translationBytes, audioBytes: audio.byteLength };
  }, browserName);
  expect(seeded.audioBytes).toBe(9644);
  await page.getByLabel(/username/i).fill("reader-a");
  await page.getByLabel(/password/i).fill("fixture-password");
  await page.getByRole("button", { name: /login|sign in/i }).click();
  await expect(page).not.toHaveURL(/login/);
  await page.evaluate(name => localStorage.setItem(name.replace(/reader-db$/, "nexus-reader-progress-queue"), JSON.stringify([
    { novelId: 42, chapter: 8, position: 27, percent: 40, ts: 1000, blocked: true, operationId: "preserve-pending-position" },
  ])), seeded.name);
  await page.goto("/offline");
  await page.getByText("Chapter readiness for Private upgraded story", { exact: true }).click();
  const story = page.getByRole("region", { name: "Offline files for Private upgraded story" });
  await expect(story.getByText("1 of 2 saved · incomplete · 1 missing", { exact: true })).toBeVisible();
  await expect(story.getByText(/Saved · matches saved text/).first()).toBeVisible();
  await expect(story.getByText("ja · Saved · source changed", { exact: true })).toBeVisible();
  await expect(story.getByText(/live work protected/)).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  const manageBounds = await page.getByRole("button", { name: "Manage offline files for Private upgraded story" }).boundingBox();
  expect(manageBounds).not.toBeNull();
  expect(manageBounds!.x).toBeGreaterThanOrEqual(0);
  expect(manageBounds!.x + manageBounds!.width).toBeLessThanOrEqual(391);
  await page.evaluate(async () => { await navigator.serviceWorker.ready; });
  await expect.poll(() => page.evaluate(() => !!navigator.serviceWorker.controller)).toBe(true);
  if ((browserName === "webkit" || browserName === "firefox")) await context.request.post("/__test/offline"); else await context.setOffline(true);
  try {
    await page.reload();
    await page.getByText("Chapter readiness for Private upgraded story", { exact: true }).click();
    await expect(page.getByText("ja · Saved · source changed", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Manage offline files for Private upgraded story" }).click();
    const selection = page.getByRole("dialog", { name: "Manage offline files for Private upgraded story" });
    const dialogBounds = await selection.boundingBox();
    expect(dialogBounds).not.toBeNull();
    expect(dialogBounds!.x).toBeGreaterThanOrEqual(0);
    expect(dialogBounds!.x + dialogBounds!.width).toBeLessThanOrEqual(391);
    await expect.poll(() => selection.evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
    await selection.getByLabel("Audio and unfinished audio parts").check();
    await selection.getByRole("button", { name: "Review cleanup", exact: true }).click();
    const review = page.getByRole("dialog", { name: "Review offline cleanup" });
    await expect(review.getByText(/Live browser audio work is protected\./)).toBeVisible();
    await expect(review.getByRole("button", { name: "Remove reviewed offline files" })).toBeDisabled();
    const actual = await page.evaluate(async name => {
      const db = await new Promise<IDBDatabase>((resolve, reject) => { const request = indexedDB.open(name); request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
      try {
        const tx = db.transaction(["offline_metadata", "chapter_audio", "chapter_audio_segments"], "readonly");
        const read = (store: string, key: string) => new Promise<Record<string, unknown>>((resolve, reject) => { const request = tx.objectStore(store).get(key); request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
        const [total, audio, segment] = await Promise.all([read("offline_metadata", "total_bytes"), read("chapter_audio", "42:22222222-2222-4222-8222-0000000186a8"), read("chapter_audio_segments", "42:22222222-2222-4222-8222-0000000186a8:0")]);
        return { version: db.version, total: total.value, audioBytes: (audio.audio_data as ArrayBuffer).byteLength,
          segmentBytes: segment.audio_data instanceof ArrayBuffer ? segment.audio_data.byteLength : (segment.audio as Blob).size, pending: localStorage.getItem(name.replace(/reader-db$/, "nexus-reader-progress-queue")) };
      } finally { db.close(); }
    }, seeded.name);
    expect(actual.version).toBe(6); expect(actual.total).toBe(seeded.expectedBytes);
    expect(actual.audioBytes).toBe(9644); expect(actual.segmentBytes).toBe(9644);
    expect(actual.pending).toContain("preserve-pending-position");
    await review.getByRole("button", { name: "Keep offline files", exact: true }).click();
    await page.getByRole("button", { name: "Manage offline files for Private upgraded story" }).click();
    await page.getByRole("dialog", { name: "Manage offline files for Private upgraded story" }).getByLabel("Translated chapters", { exact: true }).check();
    await page.getByRole("button", { name: "Review cleanup", exact: true }).click();
    const translationReview = page.getByRole("dialog", { name: "Review offline cleanup", exact: true });
    await expect(translationReview.getByRole("button", { name: "Remove reviewed offline files" })).toBeEnabled();
    await translationReview.getByRole("button", { name: "Remove reviewed offline files" }).click();
    await expect(page.getByRole("status").filter({ hasText: "Removed 2 local records" })).toBeVisible();
    const after = await page.evaluate(async name => {
      const db = await new Promise<IDBDatabase>((resolve, reject) => { const request = indexedDB.open(name); request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
      try {
        const tx = db.transaction(["offline_metadata", "translations", "chapters", "chapter_audio", "chapter_audio_segments"], "readonly");
        const total = new Promise<number>((resolve, reject) => { const request = tx.objectStore("offline_metadata").get("total_bytes"); request.onsuccess = () => resolve(request.result.value); request.onerror = () => reject(request.error); });
        const count = (store: string) => new Promise<number>((resolve, reject) => { const request = tx.objectStore(store).count(); request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
        const values = await Promise.all([total, count("translations"), count("chapters"), count("chapter_audio"), count("chapter_audio_segments")]);
        return { values, pending: localStorage.getItem(name.replace(/reader-db$/, "nexus-reader-progress-queue")) };
      } finally { db.close(); }
    }, seeded.name);
    expect(after.values).toEqual([seeded.expectedBytes - seeded.translationBytes, 0, 1, 1, 1]);
    expect(after.pending).toContain("preserve-pending-position");
    expect(serverDeletes).toEqual([]);
  } finally { await context.setOffline(false); await context.request.post("/__test/online"); }
  page.on("dialog", dialog => void dialog.accept());
  await page.goto("/more");
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page).toHaveURL(/login/);
  await page.getByLabel(/username/i).fill("reader-b");
  await page.getByLabel(/password/i).fill("fixture-password");
  await page.getByRole("button", { name: /login|sign in/i }).click();
  await expect(page).not.toHaveURL(/login/);
  await page.goto("/offline");
  await expect(page.getByText("Private upgraded story", { exact: true })).toHaveCount(0);
  const remainingQueue = await page.evaluate(name => ({
    previous: localStorage.getItem(name.replace(/reader-db$/, "nexus-reader-progress-queue")),
    current: Object.keys(localStorage).filter(key => key.includes(":6d62702d-e9e2-4a6d-97ee-9b2812a61d83:") && key.endsWith("nexus-reader-progress-queue")).map(key => localStorage.getItem(key)),
  }), seeded.name);
  expect(remainingQueue.previous).toBeNull();
  expect(remainingQueue.current.every(value => value === null || value === "[]")).toBe(true);
});

test("reviewed copies retain existing audio and translated reading through a production offline reload", async ({ page, context, browserName }, testInfo) => {
  test.skip(testInfo.config.metadata.productionOffline !== true, "Requires the production offline fixture server");
  await context.request.post("/__test/online");
  await context.request.post("/__test/rich-copies");
  const generated: string[] = [];
  page.on("request", request => {
    if (request.method() === "POST" && /\/api\/(?:audio\/.*(?:jobs|preview)|reader\/(?:translations|companion))/.test(request.url())) generated.push(request.url());
  });
  try {
    await page.goto("/login");
    await page.getByLabel(/username/i).fill("reader-a");
    await page.getByLabel(/password/i).fill("fixture-password");
    await page.getByRole("button", { name: /login|sign in/i }).click();
    await expect(page).not.toHaveURL(/login/);
    await page.goto("/library/1/novels/42");
    await page.getByRole("tab", { name: "Chapters" }).click();
    await page.getByRole("button", { name: "Manage downloads…", exact: true }).click();
    const copies = page.getByRole("dialog", { name: "Downloads and offline", exact: true });
    await copies.getByLabel("Include completed audio", { exact: true }).check();
    await copies.getByLabel("Include completed translations", { exact: true }).check();
    await copies.getByRole("button", { name: "Review all downloaded chapters", exact: true }).click();
    const review = copies.getByRole("region", { name: "Review offline copies", exact: true });
    await expect(review.getByText("12 text chapters · 1 recordings · 1 translations", { exact: true })).toBeVisible();
    await review.getByRole("button", { name: "Save reviewed offline copies", exact: true }).click();
    await expect(copies.getByRole("status").filter({ hasText: "Saved 12 chapters offline. 1 recordings saved. 1 translations saved." })).toBeVisible();
    expect(generated).toEqual([]);
    await page.goto("/offline");
    await page.getByText("Chapter readiness for Offline Fixture Story", { exact: true }).click();
    await expect(page.getByText("de · Saved · matches saved text", { exact: true })).toBeVisible();
    await page.evaluate(async () => { await navigator.serviceWorker.ready; });
    await expect.poll(() => page.evaluate(() => !!navigator.serviceWorker.controller)).toBe(true);
    if ((browserName === "webkit" || browserName === "firefox")) await context.request.post("/__test/offline"); else await context.setOffline(true);
    await page.reload();
    await page.getByText("Chapter readiness for Offline Fixture Story", { exact: true }).click();
    await expect(page.getByText("de · Saved · matches saved text", { exact: true })).toBeVisible();
    await page.goto("/library/1/novels/42/8");
    await expect(page.getByText("Offline fixture text for chapter 8.")).toBeVisible();
    await page.getByRole("button", { name: "More reader actions", exact: true }).click();
    await page.getByRole("menuitem", { name: "Translation & story companion", exact: true }).click();
    const tools = page.getByRole("dialog", { name: "Translation & story companion", exact: true });
    await tools.getByRole("button", { name: "Read translation", exact: true }).click();
    await expect(page.getByText("Offline übersetzter Kapiteltext.", { exact: true })).toBeVisible();
    expect(generated).toEqual([]);
  } finally {
    await context.setOffline(false);
    await context.request.post("/__test/online");
    await context.request.post("/__test/plain-copies");
  }
});

test("next offline selection respects negative prologues, followed custom categories and the actual unfinished position", async ({ page, context }, testInfo) => {
  test.skip(testInfo.config.metadata.productionOffline !== true, "Requires the production offline fixture server");
  test.setTimeout(60_000);
  await context.request.post("/__test/online");
  await context.request.post("/__test/selection-fixture");
  try {
    await page.goto("/login");
    await page.getByLabel(/username/i).fill("reader-a");
    await page.getByLabel(/password/i).fill("fixture-password");
    await page.getByRole("button", { name: /login|sign in/i }).click();
    await expect(page).not.toHaveURL(/login/);
    const readNumbers = () => page.evaluate(async () => {
      const suffix = ":a42a4617-a64b-440e-83bf-e52f340409f0:reader-db";
      const databases = typeof indexedDB.databases === "function" ? await indexedDB.databases() : [];
      const name = databases.find(database => database.name?.endsWith(suffix))?.name ?? `nexus-account:${encodeURIComponent(location.origin)}${suffix}`;
      const db = await new Promise<IDBDatabase>((resolve, reject) => { const request = indexedDB.open(name); request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
      try {
        const rows = await new Promise<{ novel_id: number; chapter_number: number }[]>((resolve, reject) => { const request = db.transaction("chapters", "readonly").objectStore("chapters").getAll(); request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
        return rows.filter(row => row.novel_id === 42).map(row => row.chapter_number).sort((a, b) => a - b);
      } finally { db.close(); }
    });
    const removeSavedText = async (count: number) => {
      await page.goto("/offline");
      await page.getByRole("button", { name: "Manage offline files for Offline Fixture Story", exact: true }).click();
      const dialog = page.getByRole("dialog", { name: "Manage offline files for Offline Fixture Story", exact: true });
      await dialog.getByRole("checkbox", { name: "Text and embedded images", exact: true }).check();
      await dialog.getByRole("button", { name: "Review cleanup", exact: true }).click();
      await page.getByRole("dialog", { name: "Review offline cleanup", exact: true }).getByRole("button", { name: "Remove reviewed offline files", exact: true }).click();
      await expect(page.getByRole("status").filter({ hasText: `Removed ${count} local records` })).toBeVisible();
      expect(await readNumbers()).toEqual([]);
    };
    const verifyNext = async (numbers: number[], from: number | null) => {
      await page.goto("/library/1/novels/42");
      await page.getByRole("tab", { name: "Chapters", exact: true }).click();
      await page.getByRole("button", { name: "Save next 10 offline", exact: true }).click();
      await expect(page.getByRole("status").filter({ hasText: `Saved ${numbers.length} chapter${numbers.length === 1 ? "" : "s"} offline.` })).toBeVisible();
      expect(await readNumbers()).toEqual(numbers);
      const observed = await (await context.request.get("/__test/selection-status")).json();
      expect(observed.queries).toEqual([{ followed_only: true, downloaded_only: true, from_chapter: from, offset: 0, limit: 200, total: from === 3 ? 2 : numbers.length }]);
      expect(observed.content).toEqual(numbers);
    };
    // A first reading has no invented zero boundary: negative prologue and
    // followed custom chapters are eligible; index/appendix/bonus and a
    // 20,001-missing-chapter prefix are filtered before count and pagination.
    await verifyNext([-2, -1, 1, 3, 4], null);
    await removeSavedText(5);
    await context.request.post("/__test/selection-fixture?chapter=-1&percent=50");
    await verifyNext([-1, 1, 3, 4], -1);
    await removeSavedText(4);
    // Zero is an actual saved boundary, rather than a missing-position fallback.
    await context.request.post("/__test/selection-fixture?chapter=0&percent=50");
    await verifyNext([1, 3, 4], 0);
    await removeSavedText(3);
    await context.request.post("/__test/selection-fixture?chapter=3&percent=95");
    await verifyNext([4], 3);
  } finally {
    await context.request.post("/__test/selection-reset");
    await context.request.post("/__test/online");
  }
});

test("actual signed and gapped chapter numbers drive footer, keyboard, paged edges and continuous listening", async ({ page, context }, testInfo) => {
  test.skip(testInfo.config.metadata.productionOffline !== true, "Requires the production offline fixture server");
  await context.request.post("/__test/online");
  await context.request.post("/__test/navigation-fixture");
  await page.addInitScript(() => {
    const NativeAudio = window.Audio;
    window.Audio = new Proxy(NativeAudio, { construct(target, args) {
      const audio = Reflect.construct(target, args) as HTMLAudioElement;
      (window as Window & { navigationAudio?: HTMLAudioElement }).navigationAudio = audio;
      return audio;
    } });
  });
  try {
    await page.goto("/login");
    await page.getByLabel(/username/i).fill("reader-a");
    await page.getByLabel(/password/i).fill("fixture-password");
    await page.getByRole("button", { name: /login|sign in/i }).click();
    await expect(page).not.toHaveURL(/login/);
    await page.evaluate(() => {
      const prefix = `nexus-account:${encodeURIComponent(location.origin)}:a42a4617-a64b-440e-83bf-e52f340409f0:`;
      localStorage.setItem(prefix + "nexus-reader-tts-engine", "openai_compatible");
      localStorage.setItem(prefix + "nexus-reader-tts-preset", "custom");
      localStorage.setItem(prefix + "nexus-reader-tts-execution", "server");
      localStorage.setItem(prefix + "nexus-reader-audio-continuous", "true");
    });
    await page.goto("/library/1/novels/42/-2");
    await expect(page.locator(".reader-bottombar__status").filter({ hasText: "Ch. -2 · 1 of 4" })).toBeVisible();
    const footer = page.locator(".reader-bottombar");
    await expect(footer.getByRole("button", { name: "Previous", exact: true })).toBeDisabled();
    await footer.getByRole("button", { name: "Next", exact: true }).click();
    await expect(page).toHaveURL("http://127.0.0.1:4178/library/1/novels/42/0?chapter_key=22222222-2222-4222-8222-0000000186a0");
    await expect(page.getByText("Offline fixture text for chapter 0.")).toBeVisible();
    await page.keyboard.press("ArrowRight");
    await expect(page).toHaveURL("http://127.0.0.1:4178/library/1/novels/42/3?chapter_key=22222222-2222-4222-8222-0000000186a3");
    await expect(page.locator(".reader-bottombar__status").filter({ hasText: "Ch. 3 · 3 of 4" })).toBeVisible();
    await page.keyboard.press("ArrowRight");
    await expect(page).toHaveURL("http://127.0.0.1:4178/library/1/novels/42/20007?chapter_key=22222222-2222-4222-8222-00000001d4c7");
    await expect(footer.getByRole("button", { name: "Next", exact: true })).toBeDisabled();
    await page.keyboard.press("ArrowLeft");
    await expect(page).toHaveURL("http://127.0.0.1:4178/library/1/novels/42/3?chapter_key=22222222-2222-4222-8222-0000000186a3");
    await page.evaluate(() => {
      const prefix = `nexus-account:${encodeURIComponent(location.origin)}:a42a4617-a64b-440e-83bf-e52f340409f0:`;
      localStorage.setItem(prefix + "nexus-reader-layout", "paged");
    });
    await page.reload();
    await expect(footer.getByRole("button", { name: "Next chapter", exact: true })).toBeEnabled();
    await footer.getByRole("button", { name: "Next chapter", exact: true }).click();
    await expect(page).toHaveURL("http://127.0.0.1:4178/library/1/novels/42/20007?chapter_key=22222222-2222-4222-8222-00000001d4c7");
    await expect(footer.getByRole("button", { name: "Next chapter", exact: true })).toBeDisabled();
    // A bounded live neighbor endpoint remains usable without a complete drawer.
    await context.request.post("/__test/navigation-fixture?index_unavailable");
    await page.goto("/library/1/novels/42/3");
    await expect(footer.getByRole("button", { name: "Next chapter", exact: true })).toBeEnabled();
    await footer.getByRole("button", { name: "Next chapter", exact: true }).click();
    await expect(page).toHaveURL("http://127.0.0.1:4178/library/1/novels/42/20007?chapter_key=22222222-2222-4222-8222-00000001d4c7");
    await expect(page.getByText("You’re up to date with this story.", { exact: true })).toBeVisible();
    // A cached last-chapter neighbor is a saved snapshot, not a live freshness claim.
    await context.request.post("/__test/navigation-fixture?index_unavailable&neighbors_offline");
    await page.reload();
    await expect(page.getByText("The saved chapter index ends here. Connect to check for newer chapters.", { exact: true })).toBeVisible();
    await expect(page.getByText("You’re up to date with this story.", { exact: true })).toHaveCount(0);
    await context.request.post("/__test/navigation-fixture");
    await page.goto("/library/1/novels/42/-2");
    await expect(page.locator(".reader__content")).toHaveAttribute("aria-busy", "false");
    await page.getByRole("button", { name: "Listen", exact: true }).click();
    await page.getByRole("button", { name: "Play", exact: true }).click();
    await expect.poll(() => page.evaluate(() => {
      const audio = (window as Window & { navigationAudio?: HTMLAudioElement }).navigationAudio;
      return !!audio && audio.readyState >= 2 && !audio.paused;
    })).toBe(true);
    await page.evaluate(() => (window as Window & { navigationAudio?: HTMLAudioElement }).navigationAudio!.dispatchEvent(new Event("ended")));
    await expect(page).toHaveURL("http://127.0.0.1:4178/library/1/novels/42/0?chapter_key=22222222-2222-4222-8222-0000000186a0");
    await expect(page.getByText("Offline fixture text for chapter 0.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Pause", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Pause", exact: true }).click();
    await page.screenshot({ path: `/tmp/nexus-reader-navigation-${testInfo.project.name}-desktop.png` });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: `/tmp/nexus-reader-navigation-${testInfo.project.name}-mobile.png` });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.evaluate(async () => { await document.fonts.ready; await Promise.all(document.getAnimations().filter(animation => animation.effect?.getComputedTiming().iterations !== Infinity).map(animation => animation.finished.catch(() => undefined))); });
    const accessibility = await new AxeBuilder({ page }).analyze();
    await testInfo.attach("reader-navigation-mobile-accessibility", { body: JSON.stringify(accessibility.violations, null, 2), contentType: "application/json" });
    expect(accessibility.violations).toEqual([]);
  } finally { await context.request.post("/__test/navigation-reset"); }
});
for(const legacyVersion of [4,5])test(`production v${legacyVersion} numeric cache is cleared without guessing an owner or discarding unsynchronized progress`,async({page,context},info)=>{
 test.skip(info.config.metadata.productionOffline!==true,'Requires the production offline fixture server');await context.request.post('/__test/online');await page.goto('/login');
 const seed=await page.evaluate(async version=>{
  const name=`nexus-account:${encodeURIComponent(location.origin)}:a42a4617-a64b-440e-83bf-e52f340409f0:reader-db`;
  const db=await new Promise<IDBDatabase>((resolve,reject)=>{const request=indexedDB.open(name,version);request.onupgradeneeded=()=>{const chapter=request.result.createObjectStore('chapters',{keyPath:'cache_key'});chapter.createIndex('cached_at','cached_at');chapter.createIndex('novel_id','novel_id');for(const store of ['chapter_audio','chapter_audio_jobs','translations'])request.result.createObjectStore(store,{keyPath:'cache_key'});const segments=request.result.createObjectStore('chapter_audio_segments',{keyPath:'segment_key'});segments.createIndex('cache_key','cache_key');request.result.createObjectStore('offline_metadata',{keyPath:'key'});};request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);});
  await new Promise<void>((resolve,reject)=>{const tx=db.transaction([...db.objectStoreNames],'readwrite');for(const store of ['chapters','chapter_audio','chapter_audio_jobs','translations'])tx.objectStore(store).put({cache_key:'42:0',novel_id:42,chapter_number:0,title:'Unknown numeric private original',content:'Do not bind to a replacement chapter'});tx.objectStore('chapter_audio_segments').put({segment_key:'42:0:0',cache_key:'42:0',index:0});tx.objectStore('offline_metadata').put({key:'settings',limit_bytes:123456});tx.oncomplete=()=>resolve();tx.onerror=()=>reject(tx.error);});db.close();
  const queue=name.replace(/reader-db$/,'nexus-reader-progress-queue');localStorage.setItem(queue,JSON.stringify([{novelId:42,chapter:0,position:29,percent:40,ts:1000,operationId:'keep-original-legacy-save'}]));return {name,queue};
 },legacyVersion);
 await page.getByLabel(/username/i).fill('reader-a');await page.getByLabel(/password/i).fill('fixture-password');await page.getByRole('button',{name:/login|sign in/i}).click();await expect(page).not.toHaveURL(/login/);await page.goto('/offline');await expect(page.getByText('Unknown numeric private original',{exact:true})).toHaveCount(0);
 const actual=await page.evaluate(async({name,queue})=>{const db=await new Promise<IDBDatabase>((resolve,reject)=>{const r=indexedDB.open(name);r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});try{const stores=['chapters','chapter_audio','chapter_audio_jobs','chapter_audio_segments','translations'];const tx=db.transaction([...stores,'offline_metadata'],'readonly');const counts=await Promise.all(stores.map(store=>new Promise<number>(resolve=>{const r=tx.objectStore(store).count();r.onsuccess=()=>resolve(r.result);})));return {version:db.version,counts,pending:JSON.parse(localStorage.getItem(queue)||'[]')};}finally{db.close();}},seed);
 expect(actual.version).toBe(6);expect(actual.counts).toEqual([0,0,0,0,0]);expect(actual.pending).toEqual([expect.objectContaining({chapter:0,position:29,operationId:'keep-original-legacy-save',blocked:true,conflictCode:'chapter_identity_required'})]);
});
