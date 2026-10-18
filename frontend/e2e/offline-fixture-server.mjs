// Real HTTP fixtures: service-worker requests cannot be intercepted equally
// across browsers. This server exposes only deterministic local test data.
import { createServer } from "node:http";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { resolve, extname } from "node:path";

const chapterIdentity = number => ({ chapter_key: `22222222-2222-4222-8222-${(number+100000).toString(16).padStart(12,"0")}`, manifest_epoch:"11111111-1111-4111-8111-111111111111", manifest_revision:"1" });
const root = resolve("dist");
const novel = { id: 42, library_id: 1, title: "Offline Fixture Story", author: "Fixture Author",
  url: "nexus-local:fixture", novel_site: "local", description: "Local test data", chapters: [] };
const chapters = Array.from({ length: 12 }, (_, index) => ({ ...chapterIdentity(index+1),id: 1001 + index, novel_id: 42,
  chapter_number: index + 1, title: `Chapter ${index + 1}`, category: "story", content_status: "PRESENT" }));
const mime = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json",
  ".webmanifest": "application/manifest+json", ".woff2": "font/woff2", ".woff": "font/woff", ".svg": "image/svg+xml" };
const audio = Buffer.alloc(44 + 9600);
audio.write("RIFF", 0); audio.writeUInt32LE(audio.length - 8, 4); audio.write("WAVEfmt ", 8);
audio.writeUInt32LE(16, 16); audio.writeUInt16LE(1, 20); audio.writeUInt16LE(1, 22);
audio.writeUInt32LE(16000, 24); audio.writeUInt32LE(32000, 28); audio.writeUInt16LE(2, 32);
audio.writeUInt16LE(16, 34); audio.write("data", 36); audio.writeUInt32LE(9600, 40);
const navigationAudio = Buffer.alloc(44 + 32 * 32000);
audio.copy(navigationAudio, 0, 0, 44);
navigationAudio.writeUInt32LE(navigationAudio.length - 8, 4); navigationAudio.writeUInt32LE(navigationAudio.length - 44, 40);
const selectionFollowed = ["prologue", "dream_sequence", "story"];
const selectionChapters = [
  [-3, "Appendix before opening", "appendix"], [-2, "Negative prologue", "prologue"],
  [-1, "Followed custom dream", "dream_sequence"], [0, "Index at zero", "index"],
  [1, "First story chapter", "story"], [2, "Unfollowed bonus", "bonus"],
  [3, "Followed later dream", "dream_sequence"], [4, "Later story chapter", "story"],
].map(([chapter_number, title, category], index) => ({ ...chapterIdentity(chapter_number),id: 2001 + index, novel_id: 42, chapter_number, title, category, content_status: "PRESENT" }));
// Metadata-only prefix stresses the server-side predicate before paging; none
// of these 20,001 missing originals may be fetched by the offline client.
const missingSelectionPrefix = Array.from({ length: 20_001 }, (_, index) => ({ ...chapterIdentity(-50_000+index),id: 100_000 + index, novel_id: 42,
  chapter_number: -50_000 + index, title: `Uncached earlier chapter ${index}`, category: "story", content_status: "MISSING" }));
let selectionFixture = false, selectionProgress = null;
let navigationFixture = false, navigationIndexUnavailable = false, navigationNeighborsOffline = false;
const navigationChapters = [-2, 0, 3, 20007].map((chapter_number, index) => ({ ...chapterIdentity(chapter_number),id: 3001 + index, novel_id: 42, chapter_number, title: `Navigation part ${chapter_number}`, category: "story", content_status: "PRESENT" }));
let selectionQueries = [], selectionContent = [];
const currentChapters = () => navigationFixture ? navigationChapters : selectionFixture ? selectionChapters : chapters;
let richCopies = false;
let disconnected = false;
let heldChapter = null;
const releaseChapters = new Set();
let chapterWasRequested = false;
createServer(async (request, response) => {
  const url = new URL(request.url, "http://127.0.0.1:4178");
  if (url.pathname === "/__test/navigation-fixture" || url.pathname === "/__test/navigation-reset") {
    navigationFixture = url.pathname.endsWith("navigation-fixture");
    navigationIndexUnavailable = url.searchParams.has("index_unavailable"); navigationNeighborsOffline = url.searchParams.has("neighbors_offline");
    response.writeHead(204); return response.end();
  }
  if (url.pathname === "/__test/selection-fixture") {
    selectionFixture = true;
    selectionQueries = []; selectionContent = [];
    selectionProgress = url.searchParams.has("chapter") ? { ...chapterIdentity(Number(url.searchParams.get("chapter"))),novel_id: 42, chapter_number: Number(url.searchParams.get("chapter")), position: 0,
      percent: Number(url.searchParams.get("percent") || 0), revision: 1, reading_run_key: null, updated_at: "2026-10-16T10:00:00Z" } : null;
    response.writeHead(204); return response.end();
  }
  if (url.pathname === "/__test/selection-reset") {
    selectionFixture = false; selectionProgress = null; selectionQueries = []; selectionContent = [];
    response.writeHead(204); return response.end();
  }
  if (url.pathname === "/__test/selection-status") {
    response.writeHead(200, { "Content-Type": "application/json", "Cache-Control": "no-store" });
    return response.end(JSON.stringify({ queries: selectionQueries, content: selectionContent }));
  }
  if (url.pathname === "/__test/rich-copies" || url.pathname === "/__test/plain-copies") {
    richCopies = url.pathname.endsWith("rich-copies");
    response.writeHead(204); return response.end();
  }
  if (url.pathname === "/__test/hold-chapter") {
    heldChapter = Number(url.searchParams.get("number") || 1);
    chapterWasRequested = false;
    response.writeHead(204); return response.end();
  }
  if (url.pathname === "/__test/held-chapter-status") {
    response.writeHead(200, { "Content-Type": "application/json", "Cache-Control": "no-store" });
    return response.end(JSON.stringify({ requested: chapterWasRequested }));
  }
  if (url.pathname === "/__test/release-chapter") {
    heldChapter = null;
    for (const release of releaseChapters) release();
    releaseChapters.clear();
    response.writeHead(204); return response.end();
  }
  if (url.pathname === "/__test/online" || url.pathname === "/__test/offline") {
    disconnected = url.pathname.endsWith("offline"); response.writeHead(204); return response.end();
  }
  if (disconnected) return request.socket.destroy();
  const json = (value, status = 200) => { response.writeHead(status, { "Content-Type": "application/json", "Cache-Control": "no-store" }); response.end(JSON.stringify(value)); };
  if (url.pathname.startsWith("/api/")) {
    const path = url.pathname.slice(4);
    if (path === "/auth/config") return json({ signup_mode: "open", first_user: false });
    if (path === "/auth/login" || path === "/auth/refresh") {
      let id = request.headers.cookie?.includes("fixture-user=8") ? 8 : request.headers.cookie?.includes("fixture-user=7") ? 7 : null;
      if (path.endsWith("login")) {
        let body = ""; for await (const chunk of request) body += chunk;
        id = JSON.parse(body).username === "reader-b" ? 8 : 7;
      }
      if (!id) return json({ detail: "Not signed in" }, 401);
      response.setHeader("Set-Cookie", `fixture-user=${id}; HttpOnly; SameSite=Lax; Path=/`);
      return json({ id, storage_id: id === 7 ? "a42a4617-a64b-440e-83bf-e52f340409f0" : "6d62702d-e9e2-4a6d-97ee-9b2812a61d83", username: id === 7 ? "reader-a" : "reader-b", is_admin: false, access_token: `fixture-${id}`, token_type: "bearer", expires_in: 900 });
    }
    if (path === "/auth/logout") {
      response.setHeader("Set-Cookie", "fixture-user=; Max-Age=0; Path=/"); return json({});
    }
    const id = request.headers.authorization === "Bearer fixture-7" ? 7 : request.headers.authorization === "Bearer fixture-8" ? 8 : null;
    if (!id) return json({ detail: "Not signed in" }, 401);
    if (id === 8 && (path.startsWith("/chapter/") || path.startsWith("/novel/42") || path.startsWith("/reader/stories/42/") || path.startsWith("/reader/offline/") || path.startsWith("/audio/"))) return json({ detail: "Story not found" }, 404);
    if (path === "/library/" || path === "/library") return json([{ id: 1, name: "Reading Library" }]);
    if (path === "/novel/42") return json(novel);
    if (path === "/chapter/reading-summary/42" || path === "/chapter/reading-chapters/42" || path === "/chapter/novel/42/download-status") {
      const rows=currentChapters(), followed=selectionFixture?selectionFollowed:["story"];
      const progress=selectionFixture?selectionProgress:null;
      if(path.endsWith("/download-status")) return json({total:rows.length,present:rows.filter(row=>row.content_status==="PRESENT").length,missing:rows.filter(row=>row.content_status==="MISSING").length,failed:0,processing:0,failed_chapters:[],processing_chapters:[]});
      if(path.includes("/reading-summary/")) {
        const index=progress?rows.findIndex(row=>row.chapter_number===progress.chapter_number):-1;
        return json({novel_id:42,reading_run_key:null,revision:progress?.revision??0,total_chapters:rows.length,followed_total:rows.filter(row=>followed.includes(row.category)).length,completed_chapters:0,followed_completed_chapters:0,completion_basis:"recorded_checkpoints",completed_reading:false,current:progress?{chapter_id:rows[index]?.id??null,chapter_number:progress.chapter_number,ordinal:index<0?null:index+1,followed_ordinal:null,percent:progress.percent}:null,next_unread_chapter_id:rows.find(row=>followed.includes(row.category))?.id??null,next_unread_chapter_number:rows.find(row=>followed.includes(row.category))?.chapter_number??null,categories:[...new Set(rows.map(row=>row.category))],categories_truncated:false});
      }
      const offset=Number(url.searchParams.get("offset")||0),limit=Number(url.searchParams.get("limit")||100),q=(url.searchParams.get("q")||"").trim().toLowerCase();
      const selected=rows.map((row,index)=>({...row,audio_status:"MISSING",created_at:"2026-10-16T00:00:00Z",updated_at:"2026-10-16T00:00:00Z",ordinal:index+1,followed_ordinal:followed.includes(row.category)?rows.slice(0,index+1).filter(item=>followed.includes(item.category)).length:null,followed:followed.includes(row.category),completed_checkpoint:false,max_percent:null})).filter(row=>(url.searchParams.get("category_scope")!=="followed"||row.followed)&&(!q||row.title.toLowerCase().includes(q)||String(row.chapter_number).includes(q)));
      return json({novel_id:42,reading_run_key:null,revision:progress?.revision??0,total:selected.length,offset,limit,items:selected.slice(offset,offset+limit)});
    }
    if (path === "/chapter/42") {
      if (navigationFixture && navigationIndexUnavailable) return json({ detail: "Chapter drawer unavailable" }, 503);
      const skip = Number(url.searchParams.get("skip") || 0), limit = Number(url.searchParams.get("limit") || 1000);
      return json(currentChapters().slice(skip, skip + limit));
    }
    const navigation = path.match(/^\/chapter\/navigation\/42\/(-?\d+)$/);
    if (navigation) {
      if (navigationFixture && navigationNeighborsOffline) return request.socket.destroy();
      const rows = currentChapters(), index = rows.findIndex(row => row.chapter_number === Number(navigation[1]));
      if (index < 0) return json({ detail: "Chapter not found" }, 404);
      const entry = row => row ? { ...chapterIdentity(row.chapter_number),id: row.id, chapter_number: row.chapter_number, title: row.title } : null;
      return json({ ...chapterIdentity(rows[index].chapter_number),novel_id: 42, chapter_id: rows[index].id, chapter_number: rows[index].chapter_number, previous: entry(rows[index - 1]), next: entry(rows[index + 1]) });
    }
    if (path === "/reader/stories/42/offline-manifest") {
      const offset = Number(url.searchParams.get("offset") || 0);
      const limit = Number(url.searchParams.get("limit") || 100);
      const followedOnly = url.searchParams.get("followed_only") === "true";
      const downloadedOnly = url.searchParams.get("downloaded_only") === "true";
      const fromChapter = url.searchParams.has("from_chapter") ? Number(url.searchParams.get("from_chapter")) : null;
      const followed = selectionFixture ? selectionFollowed : ["story"];
      const manifestChapters = selectionFixture ? [...missingSelectionPrefix, ...selectionChapters] : currentChapters();
      const selected = manifestChapters.filter(chapter => (!followedOnly || followed.includes(chapter.category || "story"))
        && (!downloadedOnly || chapter.content_status === "PRESENT") && (fromChapter === null || chapter.chapter_number >= fromChapter));
      if (selectionFixture) selectionQueries.push({ followed_only: followedOnly, downloaded_only: downloadedOnly, from_chapter: fromChapter, offset, limit, total: selected.length });
      return json({ manifest_epoch:chapterIdentity(1).manifest_epoch,manifest_revision:"1",novel_id: 42, library_id: 1, novel_title: novel.title, total: selected.length, offset, limit,
        chapters: selected.slice(offset, offset + limit).map(chapter => {
          const text = `Offline fixture text for chapter ${chapter.chapter_number}.`;
          const source_version = chapter.chapter_number === 8 ? "8".repeat(64)
            : createHash("sha256").update(`<p>${text}</p>`).digest("hex");
          return { ...chapterIdentity(chapter.chapter_number),id: chapter.id, chapter_number: chapter.chapter_number, title: chapter.title,
            downloaded: chapter.content_status === "PRESENT", source_version: chapter.content_status === "PRESENT" ? source_version : null, text_bytes_estimate: chapter.content_status === "PRESENT" ? Buffer.byteLength(text) : 0,
            audio: richCopies && chapter.chapter_number === 8 ? { job_id: 808, bytes: audio.length, source_version } : null,
            translations: richCopies && chapter.chapter_number === 8 ? [{ job_id: 1808, language: "de", bytes_estimate: 256, source_version }] : [], translations_limited: false };
        }),
      });
    }
    if (navigationFixture && path === "/audio/jobs" && request.method === "GET") {
      const row = navigationChapters.find(row => row.id === Number(url.searchParams.get("chapter_id")));
      return json(row ? [{ ...chapterIdentity(row.chapter_number),id: row.id + 5000, status: "completed", provider_id: "custom", provider_model: "fixture", provider_voice: "fixture", total_parts: 1, completed_parts: 1, audio_ready: true }] : []);
    }
    const navigationRecording = path.match(/^\/audio\/jobs\/(\d+)\/(audio|manifest)$/);
    if (navigationFixture && navigationRecording) {
      const row = navigationChapters.find(row => row.id + 5000 === Number(navigationRecording[1]));
      if (!row) return json({ detail: "Recording not found" }, 404);
      if (navigationRecording[2] === "audio") { response.writeHead(200, { "Content-Type": "audio/wav", "Content-Length": navigationAudio.length }); return response.end(navigationAudio); }
      const text = `Offline fixture text for chapter ${row.chapter_number}.`, version = createHash("sha256").update(`<p>${text}</p>`).digest("hex");
      return json({ ...chapterIdentity(row.chapter_number),job_id: row.id + 5000, source_version: version, rendition: "original", include_author_notes: false, precision: "segment", current_source: true, duration_seconds: 32,
        segments: [{ part_index: 0, start_seconds: 0, end_seconds: 32, block_id: `b-${version.slice(0, 24)}-0`, text_offset: 0, text_length: text.length }] });
    }
    if (path === "/audio/jobs/808/audio") {
      response.writeHead(200, { "Content-Type": "audio/wav", "Content-Length": audio.length, "Cache-Control": "private, no-store" });
      return response.end(audio);
    }
    if (path === "/audio/jobs/808/manifest") return json({ ...chapterIdentity(8),job_id: 808, source_version: "8".repeat(64),
      rendition: "original", include_author_notes: false, precision: "segment", current_source: true,
      duration_seconds: .3, segments: [{ part_index: 0, start_seconds: 0, end_seconds: .3,
        block_id: "offline-illustration", text_offset: 0, text_length: "Offline fixture text for chapter 8.".length }] });
    if (path === "/reader/offline/translations/1808") return json({ ...chapterIdentity(8),id: 1808, novel_id: 42, chapter_id: 1008,
      chapter_number: 8, language: "de", status: "completed", provider: { kind: "local", model: "fixture" },
      source_version: "8".repeat(64), completed_blocks: 1, total_blocks: 1, charged_usd: 0, error: null,
      document: { schema_version: 1, source_format: "html", content_version: "b".repeat(64),
        plain_text: "Offline übersetzter Kapiteltext.", blocks: [{ id: "offline-illustration", kind: "p",
          text: "Offline übersetzter Kapiteltext.", html: "<p>Offline übersetzter Kapiteltext.</p>" }] } });
    if (path === "/chapter/progress/42" && request.method === "GET") return json(selectionFixture ? selectionProgress : null);
    if (path === "/chapter/progress/42") return json({ revision: 1 });
    const content = path.match(/^\/chapter\/content\/library\/1\/42\/(-?\d+)$/);
    if (content) {
      const sourceChapter = currentChapters().find(chapter => chapter.chapter_number === Number(content[1]));
      if (!sourceChapter) return json({ detail: "Chapter not found" }, 404);
      if (selectionFixture) selectionContent.push(Number(content[1]));
      if (Number(content[1]) === heldChapter) {
        chapterWasRequested = true;
        await new Promise(resolveRequest => { releaseChapters.add(resolveRequest); });
      }
      const text = `Offline fixture text for chapter ${content[1]}.`;
      const html = `<p>${text}</p>`, version = createHash("sha256").update(html).digest("hex");
      const result = { ...sourceChapter, content: text, document: {
        schema_version: 1, source_format: "text", content_version: version, plain_text: text,
        blocks: [{ id: `b-${version.slice(0, 24)}-0`, kind: "p", text, html }],
      } };
      // Match the current backend: legacy plain text receives a deterministic
      // document; one chapter also includes a stored illustration.
      if (Number(content[1]) === 8) result.document = {
        schema_version: 1, source_format: "html", content_version: "8".repeat(64), plain_text: text,
        blocks: [{ id: "offline-illustration", kind: "p", text, html: `<p>${text}<img alt="Offline island map" src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNQ6pgJAAITAUTGjr3DAAAAAElFTkSuQmCC"></p>` }],
      };
      result.source_version=result.document.content_version;result.current_content_version=result.document.content_version;
      return json(result);
    }
    if (path === "/personal/novels/42") return json({ novel_id: 42, notes: null, rating: null, user_tags: [], shelf_ids: [], followed_categories: selectionFixture ? selectionFollowed : ["story"], auto_download: false, keep_ahead: 5 });
    if (path === "/personal/tags") return json({ tags: [] });
    if (path.startsWith("/stats/")) return json({ reading_seconds: 0, chapters_read: 0, words_read: 0, novels_finished: 0 });
    if (path.startsWith("/sources/")) return json({ sources: [] });
    if (path.startsWith("/novel/")) return json([]);
    return json([]);
  }
  const requested = resolve(root, `.${url.pathname}`);
  if (requested !== root && !requested.startsWith(root + "/")) { response.writeHead(404); return response.end(); }
  try {
    let data, file = requested;
    try { data = await readFile(file); } catch { file = resolve(root, "index.html"); data = await readFile(file); }
    response.writeHead(200, { "Content-Type": mime[extname(file)] || "application/octet-stream" }); response.end(data);
  } catch { response.writeHead(500); response.end(); }
}).listen(4178, "127.0.0.1");
