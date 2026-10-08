import { BrowserContext, Page, Route } from "@playwright/test";

type MockApiOptions = {
  admin?: boolean;
  previewFailure?: "timeout" | "source";
  signupMode?: "open" | "invite" | "closed";
};

type MockUser = { id: number; username: string; is_admin: boolean; is_disabled: boolean; active_sessions: number };

/** Handles the tests use to change the fake server's state mid-test. */
export type MockApi = {
  /** End every session, as "sign out other devices" or an admin would. */
  revokeSessions: () => void;
  /** An invite code the fake server accepts once. */
  addInvite: (code: string) => void;
  /** A password reset token the fake server accepts once. */
  addResetToken: (token: string) => void;
};

const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });

const pathAndQuery = (route: Route) => {
  const url = new URL(route.request().url());
  // Local Vite tests use the host API directly; Compose uses nginx's /api
  // prefix. Exercise the same logical routes in both cases.
  return `${url.pathname.replace(/^\/api(?=\/|$)/, "")}${url.search}`;
};

const STORY_CATALOG = {
  4: {
    id: 4, title: "The Quiet Ledger", author: "Mara Thorne", author_id: 1, source_url: "https://www.royalroad.com/fiction/4/the-quiet-ledger",
    novel_site: "royalroad", img_url: null, word_count: 412000, views: 120000, favorites: 3400, follows: 5100, reviews: 80, rating: 4.6,
    status: "Ongoing", chapter_count: 3, created_at: "2025-03-02T12:00:00Z", updated_at: "2026-07-26T10:00:00Z",
    description: "Orren Vael keeps the books for a guild of second-rate mages, and he would like it to stay that way.",
    tags: ["Progression", "Slow burn", "Political intrigue"], genres: ["Fantasy"], fandoms: [],
  },
  5: {
    id: 5, title: "The Cartographer's Apprentice", author: "Ilse Marrow", author_id: 2, source_url: "https://www.scribblehub.com/series/5/",
    novel_site: "scribblehub", img_url: null, word_count: 98000, views: null, favorites: null, follows: null, reviews: null, rating: null,
    status: null, chapter_count: 21, created_at: "2026-01-02T12:00:00Z", updated_at: "2026-07-20T10:00:00Z",
    description: "A mapmaker's apprentice charts a city that redraws itself.", tags: ["Adventure"], genres: [], fandoms: [],
  },
} as const;

const STORY_CHAPTERS = [
  { id: 101, novel_id: 11, chapter_number: 1, title: "A Correction, Filed in Triplicate", content_status: "PRESENT", category: "story" },
  { id: 102, novel_id: 11, chapter_number: 2, title: "Interest Compounds", content_status: "PRESENT", category: "story" },
  { id: 103, novel_id: 11, chapter_number: 3, title: "The Second Column", content_status: "MISSING", category: "story" },
  { id: 104, novel_id: 11, chapter_number: 4, title: "Author's note", content_status: "MISSING", category: "author_note" },
];

/** Story page fixtures; undefined when the path is not a story request. */
const storyFixture = (path: string): unknown => {
  const [pathname] = path.split("?");
  const catalog = pathname.match(/^\/discovery\/novels\/(4|5)(\/[a-z-]+)?$/);
  if (catalog) {
    const id = Number(catalog[1]) as 4 | 5;
    switch (catalog[2]) {
      case undefined: return STORY_CATALOG[id];
      case "/analysis": return { state: "completed", signals: [{ family: "point_of_view", value: "third person", confidence: 0.8, evidence: {}, model_version: "fixture" }] };
      case "/similar": return { results: [{ novel_id: id === 4 ? 5 : 4, title: STORY_CATALOG[id === 4 ? 5 : 4].title, author: "Fixture Author", score: 0.7, explanation: "Shared tags", reasons: ["Both follow a reluctant expert"] }] };
      case "/editions": return { id: 1, title: "The Quiet Ledger", editions: [{ id: 1, novel_id: id, edition_kind: "original", language: "en" }] };
      case "/story-guide": return { chapters_analyzed: 0, through_chapter: 0, characters: [], chapters: [] };
      default: return undefined;
    }
  }
  if (pathname === "/stories/4") {
    return { metadata_id: 4, library_entries: [{ novel_id: 11, library_id: 1, library_name: "Reading Library", title: "The Quiet Ledger", follow_state: "reading", scrape_status: "completed" }] };
  }
  if (pathname === "/stories/5") return { metadata_id: 5, library_entries: [] };
  if (pathname === "/novel/11") {
    const base = STORY_CATALOG[4];
    return {
      ...base, id: 11, library_id: 1, metadata_id: 4, url: base.source_url, novel_site: "royalroad", cover_image: null, story_id: 4,
      author_site_id: null, publish_date: "2025-03-02T12:00:00Z", updated_date: base.updated_at, analyzed_at: null, analysis_type: null,
      analyzed_chapter_count: null, parsed_at: "2026-07-26T11:50:00Z", scrape_status: "completed", scrape_error: null,
      follow_state: "reading", followed_at: "2026-07-01T12:00:00Z", next_unread_chapter_number: 2, next_unread_chapter_id: 102,
    };
  }
  if (pathname === "/novel/11/follow") {
    return { novel_id: 11, follow_state: "reading", download_policy: "none", download_count: 1, notification_policy: "immediate", notification_count: 1 };
  }
  if (pathname === "/chapter/11") return STORY_CHAPTERS;
  if (pathname === "/chapter/progress/11") return { chapter_number: 1 };
  if (pathname === "/personal/novels/11") {
    return { novel_id: 11, notes: "Re-read the guild audit arc.", rating: 4, user_tags: ["cozy"], followed_categories: ["story"], auto_download: true, keep_ahead: 5 };
  }
  return undefined;
};

// Pass the browser context instead of a page when a service worker is active:
// requests the worker makes are only visible to context routes.
export async function installMockApi(page: Page | BrowserContext, options: MockApiOptions = {}): Promise<MockApi> {
  let catalogJobStatus = "running";
  let previewCalls = 0;
  // The fake server mirrors the real session model: the refresh "cookie" is
  // this flag (the page keeps it across reloads), access tokens are
  // numbered, and revoking sessions invalidates all of them at once.
  let signedIn = false;
  let signedInUser = authUser.username;
  let tokenCounter = 0;
  const validTokens = new Set<string>();
  let signupMode = options.signupMode ?? "open";
  const invites = new Set<string>();
  const resetTokens = new Set<string>();
  const users: MockUser[] = [
    { id: 7, username: authUser.username, is_admin: !!options.admin, is_disabled: false, active_sessions: 1 },
    { id: 8, username: "second-reader", is_admin: false, is_disabled: false, active_sessions: 0 },
  ];

  const startSession = (username: string) => {
    signedIn = true;
    signedInUser = username;
    tokenCounter += 1;
    const accessToken = `e2e-token-${tokenCounter}`;
    validTokens.add(accessToken);
    return {
      access_token: accessToken,
      token_type: "bearer",
      expires_in: 900,
      id: 7,
      username,
      is_admin: !!options.admin,
      message: "authenticated",
    };
  };

  const api: MockApi = {
    revokeSessions: () => {
      signedIn = false;
      validTokens.clear();
    },
    addInvite: (code) => invites.add(code),
    addResetToken: (token) => resetTokens.add(token),
  };

  await page.route(/127\.0\.0\.1:8000|localhost:8000|\/api\//, async (route) => {
    const request = route.request();
    const path = pathAndQuery(route);
    const method = request.method();

    if (path === "/auth/login") {
      const data = request.postDataJSON() as { username?: string; password?: string };
      if (data.username === "invalid") {
        await json(route, { detail: "Invalid credentials" }, 401);
        return;
      }
      await json(route, startSession(data.username || authUser.username));
      return;
    }
    if (path === "/auth/signup") {
      const data = request.postDataJSON() as { username?: string; invite_code?: string };
      if (signupMode === "closed") {
        await json(route, { detail: "Sign-up is closed on this instance." }, 403);
        return;
      }
      if (signupMode === "invite") {
        if (!data.invite_code || !invites.has(data.invite_code)) {
          await json(route, { detail: "This invite code is not valid." }, 403);
          return;
        }
        invites.delete(data.invite_code);
      }
      await json(route, startSession(data.username || authUser.username), 201);
      return;
    }
    if (path === "/auth/refresh") {
      if (!signedIn) {
        await json(route, { detail: "Session ended. Please sign in again." }, 401);
        return;
      }
      await json(route, startSession(signedInUser));
      return;
    }
    if (path === "/auth/logout") {
      api.revokeSessions();
      await route.fulfill({ status: 204 });
      return;
    }
    if (path === "/auth/config") {
      await json(route, { signup_mode: signupMode, first_user: false });
      return;
    }
    if (path === "/auth/password-reset") {
      const data = request.postDataJSON() as { token?: string };
      if (!data.token || !resetTokens.has(data.token)) {
        await json(route, { detail: "This password reset link is invalid or has expired." }, 400);
        return;
      }
      resetTokens.delete(data.token);
      await json(route, { message: "Password changed. Please sign in." });
      return;
    }

    // Everything else needs a live access token, like the real API.
    const authorization = request.headers()["authorization"] || "";
    if (!validTokens.has(authorization.replace(/^Bearer /, ""))) {
      await json(route, { detail: "Session ended. Please sign in again." }, 401);
      return;
    }

    if (path === "/auth/logout-others" && method === "POST") {
      await json(route, { revoked_sessions: 2 });
      return;
    }
    if (path.startsWith("/admin/")) {
      if (!options.admin) {
        await json(route, { detail: "Administrator access required" }, 403);
        return;
      }
      if (path === "/admin/users" && method === "GET") {
        await json(route, users.map((user) => ({ ...user, created_at: "2026-07-26T12:00:00Z", last_seen_at: null })));
        return;
      }
      const userMatch = path.match(/^\/admin\/users\/(\d+)(\/password-reset)?$/);
      if (userMatch) {
        const user = users.find((item) => item.id === Number(userMatch[1]))!;
        if (userMatch[2]) {
          resetTokens.add("reset-from-admin");
          await json(route, { token: "reset-from-admin", path: "/reset-password?token=reset-from-admin", expires_at: "2026-07-27T12:00:00Z" });
          return;
        }
        Object.assign(user, request.postDataJSON());
        await json(route, { ...user, created_at: null, last_seen_at: null });
        return;
      }
      if (path === "/admin/settings") {
        if (method === "PUT") signupMode = request.postDataJSON().signup_mode;
        await json(route, { signup_mode: signupMode });
        return;
      }
      if (path === "/admin/invites" && method === "POST") {
        invites.add("fresh-invite-code");
        await json(route, { id: 1, label: request.postDataJSON().label ?? null, max_uses: 1, use_count: 0, expires_at: null, revoked_at: null, created_at: null, status: "active", code: "fresh-invite-code" }, 201);
        return;
      }
      if (path === "/admin/invites") {
        await json(route, [...invites].map((_code, index) => ({ id: index + 1, label: "Fixture invite", max_uses: 1, use_count: 0, expires_at: null, revoked_at: null, created_at: null, status: "active", code: null })));
        return;
      }
    }
    if (!options.admin && path.startsWith("/catalog-scrapes")) {
      await json(route, { detail: "Administrator access is required." }, 403);
      return;
    }
    // Story page (D9): catalog story 4 is in library 1 as novel 11; story 5 is catalog-only.
    const story = storyFixture(path);
    if (story !== undefined) {
      await json(route, story);
      return;
    }
    if (path === "/library/" || path === "/library") {
      await json(route, [{ id: 1, name: "Reading Library", description: "Deterministic E2E library" }]);
      return;
    }
    if (path.startsWith("/operations/summary")) {
      await json(route, {
        library_id: 1,
        followed_stories: 3,
        reading_stories: 1,
        unread_updates: 2,
        source_failures: 1,
        downloads: { queued: 2, running: 1, completed: 8, failed: 1, cancelled: 0 },
        metadata_server: { status: "online", detail: "Fixture metadata service ready", checked_at: "2026-07-26T12:00:00Z" },
        metadata_jobs: { queued: 1, running: 1, completed: 8, failed: 1, cancelled: 0 },
        source_health: { fanfiction: 1 },
        refresh_schedules: 1,
        generated_at: "2026-07-26T12:00:00Z",
      });
      return;
    }
    if (path.startsWith("/operations/schedules") && method === "GET") {
      await json(route, [{ id: "schedule-1", site: "fanfiction", interval_minutes: 360, batch_size: 100, enabled: true, next_run_at: "2026-07-27T00:00:00Z" }]);
      return;
    }
    if (path.startsWith("/operations/metadata-jobs") && method === "GET") {
      await json(route, { data: [{ id: "metadata-1", job_type: "source_refresh", site: "fanfiction", status: "failed", message: "Source timed out", attempt_count: 2, max_attempts: 3, retryable: true, error_code: "timeout", results: {} }] });
      return;
    }
    if (path.startsWith("/operations/source-health")) {
      await json(route, [{ site: "fanfiction", status: "degraded", circuit_state: "half_open", failure_count: 1, last_latency_ms: 1200, last_success_at: "2026-07-26T11:58:00Z", last_failure_at: "2026-07-26T11:59:00Z", last_error_code: "timeout", last_error: "Fixture timeout" }]);
      return;
    }
    if (path.startsWith("/operations/source-policy")) {
      await json(route, { hours: 24, sources: [{ site: "fanfiction", requests: 4, cache_hit_percent: 25, average_latency_ms: 1200, last_request_at: "2026-07-26T11:59:00Z", circuit_state: "half_open", last_error_category: "timeout", average_job_duration_seconds: 3, retention_days: 30 }] });
      return;
    }
    if (path.startsWith("/shelves") && method === "GET") {
      await json(route, []);
      return;
    }
    if (path.startsWith("/personal/tags")) {
      await json(route, { tags: [] });
      return;
    }
    if (path.startsWith("/activity/inbox") || path.startsWith("/activity/calendar")) {
      await json(route, []);
      return;
    }
    if (path.startsWith("/activity/feed") || path.startsWith("/novel/updates")) {
      await json(route, []);
      return;
    }
    if (path === "/catalog-scrapes/capabilities") {
      const capability = { site: "fanfiction", name: "FanFiction.net", adapter_version: 2, modes: ["top_rated", "newest", "most_reviewed", "most_favorited", "most_followed", "genre", "crossover", "search", "custom_urls"], filters: ["fandoms", "genres", "rating", "language", "status", "word_count", "statistics"], remote_filters: ["fandoms", "genres", "rating", "language", "status", "word_count", "statistics"], local_filters: ["min_words", "min_favorites", "min_follows", "min_reviews"], media: [{ value: "book", label: "Books" }, { value: "tv", label: "TV Shows" }], rate_limit: "1 request/sec", policy: "Fixture source" };
      await json(route, { sources: [capability], default_site: "fanfiction", version: 2 });
      return;
    }
    if (path.startsWith("/catalog-scrapes/taxonomies/")) {
      await json(route, [{ display_value: "Harry Potter", source_value: "224", story_count: 1000, observed_at: "2026-07-26T12:00:00Z" }, { display_value: "Game of Thrones", source_value: "8324", story_count: 500, observed_at: "2026-07-26T12:00:00Z" }]);
      return;
    }
    if (path === "/catalog-scrapes" && method === "GET") {
      await json(route, []);
      return;
    }
    if (path === "/catalog-scrapes/preview" && method === "POST") {
      previewCalls += 1;
      if (options.previewFailure === "timeout" && previewCalls === 1) {
        await route.abort("timedout");
        return;
      }
      if (options.previewFailure === "source") {
        await json(route, { detail: "FanFiction.net did not respond in time. No job was created; retry after the source recovers." }, 503);
        return;
      }
      const query = request.postDataJSON()?.query || {};
      await json(route, {
        query,
        source_url: "https://www.fanfiction.net/tv/Game-of-Thrones/?srt=1&p=1",
        capabilities: { modes: [], filters: [], remote_filters: ["fandom", "sort"], local_filters: ["min_words", "min_favorites"], rate_limit: "1 request/sec" },
        estimated_pages: 2,
        matched_count: 1,
        warnings: ["Minimum words and favorites are applied locally."],
        preview: [{ title: "A Fixture Story", author: "Fixture Author", source_url: "https://www.fanfiction.net/s/123456/1/a-fixture-story", word_count: 25000, favorites: 42, reviews: 12, follows: 18, status: "In-Progress", updated: "2026-07-25", matched: true }],
      });
      return;
    }
    if (path === "/catalog-scrapes" && method === "POST") {
      await json(route, { definition: { id: 12, name: "Game of Thrones — Newest Stories", site: "fanfiction", enabled: true, schedule_interval_minutes: null }, job: { id: "catalog-1", job_type: "catalog_scrape", site: "fanfiction", status: "running", progress: 0.25, message: "Scanning page 1", results: { pages_scanned: 1, candidates_found: 1, queued_imports: 1 }, attempt_count: 1, retryable: true, retry_cycle: 1 } });
      return;
    }
    if (path.startsWith("/catalog-scrapes/jobs/") && path.endsWith("/candidates?limit=100")) {
      await json(route, [{ id: 1, source_url: "https://www.fanfiction.net/s/123456/1/a-fixture-story", candidate_status: "matched", listing_metadata: { title: "A Fixture Story" } }]);
      return;
    }
    if (/^\/catalog-scrapes\/jobs\/[^/]+\/candidates\/\d+$/.test(path) && method === "PATCH") {
      await json(route, { id: 1, source_url: "https://www.fanfiction.net/s/123456/1/a-fixture-story", candidate_status: "ignored", skip_reason: "Ignored by administrator", listing_metadata: { title: "A Fixture Story" } });
      return;
    }
    if (path.startsWith("/catalog-scrapes/jobs/") && method === "GET") {
      await json(route, { id: "catalog-1", job_type: "catalog_scrape", site: "fanfiction", status: catalogJobStatus, progress: catalogJobStatus === "cancelled" ? 0.25 : 0.75, message: catalogJobStatus === "cancelled" ? "Cancelled by user" : "Scanning page 2", results: { pages_scanned: 2, candidates_found: 1, queued_imports: 1 }, attempt_count: 1, retryable: true, retry_cycle: 1 });
      return;
    }
    if (path.endsWith("/cancel") && method === "POST") {
      catalogJobStatus = "cancelled";
      await json(route, { id: "catalog-1", job_type: "catalog_scrape", site: "fanfiction", status: catalogJobStatus, progress: 0.25, message: "Cancelled by user", results: { pages_scanned: 1 }, attempt_count: 1, retryable: true, retry_cycle: 1 });
      return;
    }
    if (path.endsWith("/retry") && method === "POST") {
      catalogJobStatus = "running";
      await json(route, { id: "catalog-1", job_type: "catalog_scrape", site: "fanfiction", status: catalogJobStatus, progress: 0, message: "Manual retry started", results: {}, attempt_count: 1, retryable: true, retry_cycle: 2 });
      return;
    }
    if (path.startsWith("/operations/metadata-jobs/") && method === "POST") {
      await json(route, { id: "metadata-1", job_type: "source_refresh", site: "fanfiction", status: "queued", attempt_count: 1, max_attempts: 3, retryable: true, error_code: null, results: {} });
      return;
    }
    // Keep incidental layout requests deterministic and non-blocking.
    await json(route, {});
  });

  return api;
}

export const authUser = { username: "e2e-user", password: "NexusE2E-1234" };
