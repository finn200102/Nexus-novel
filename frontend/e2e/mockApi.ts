import { Page, Route } from "@playwright/test";

type MockApiOptions = {
  admin?: boolean;
  previewFailure?: "timeout" | "source";
};

const token = "e2e-token";

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

export async function installMockApi(page: Page, options: MockApiOptions = {}) {
  let catalogJobStatus = "running";
  let previewCalls = 0;

  await page.route(/\/auth\/login$|\/auth\/signup$/, async (route) => {
    const request = route.request();
    const data = request.postDataJSON() as { username?: string; password?: string };
    if (request.url().endsWith("/auth/login") && data.username === "invalid") {
      await json(route, { detail: "Invalid credentials" }, 401);
      return;
    }
    await json(route, {
      access_token: token,
      token_type: "bearer",
      id: 7,
      username: data.username || "e2e-user",
      message: "authenticated",
    });
  });

  await page.route(/127\.0\.0\.1:8000|localhost:8000|\/api\//, async (route) => {
    const request = route.request();
    const path = pathAndQuery(route);
    const method = request.method();

    if (path.startsWith("/auth/login") || path.startsWith("/auth/signup")) {
      const data = request.postDataJSON() as { username?: string; password?: string };
      if (path.startsWith("/auth/login") && data.username === "invalid") {
        await json(route, { detail: "Invalid credentials" }, 401);
        return;
      }
      await json(route, { access_token: token, token_type: "bearer", id: 7, username: "e2e-user", message: "authenticated" });
      return;
    }
    if (!options.admin && path.startsWith("/catalog-scrapes")) {
      await json(route, { detail: "Administrator access is required." }, 403);
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
    if (path.startsWith("/activity/feed") || path.startsWith("/novel/updates")) {
      await json(route, []);
      return;
    }
    if (path === "/catalog-scrapes/capabilities") {
      await json(route, { modes: ["top_rated", "newest", "most_reviewed", "most_favorited", "most_followed", "genre", "crossover", "search", "custom_urls"], filters: ["fandom", "genres", "rating", "language", "status", "word_count", "statistics"], media: [{ value: "book", label: "Books" }, { value: "tv", label: "TV Shows" }], rate_limit: "1 request/sec" });
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
      await json(route, [{ id: 1, source_url: "https://www.fanfiction.net/s/123456/1/a-fixture-story", candidate_status: "import_queued", listing_metadata: { title: "A Fixture Story" } }]);
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
}

export const authUser = { username: "e2e-user", password: "NexusE2E-1234" };
