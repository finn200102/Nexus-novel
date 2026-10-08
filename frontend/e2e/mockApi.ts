import { Page, Route } from "@playwright/test";

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

export async function installMockApi(page: Page, options: MockApiOptions = {}): Promise<MockApi> {
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
