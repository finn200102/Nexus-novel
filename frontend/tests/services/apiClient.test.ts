import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import axios, { AxiosAdapter, AxiosError, InternalAxiosRequestConfig } from "axios";
import apiClient, { hasAccessToken, onSessionChange, refreshSession, setSession } from "../../src/services/apiClient";

const session = (token: string) => ({
  id: 1,
  username: "reader",
  message: "ok",
  access_token: token,
  token_type: "bearer",
  expires_in: 900,
});

const respond = (config: InternalAxiosRequestConfig, status: number, data: unknown) => {
  const response = { data, status, statusText: String(status), headers: {}, config };
  if (status >= 400) {
    return Promise.reject(new AxiosError(`HTTP ${status}`, String(status), config, null, response));
  }
  return Promise.resolve(response);
};

describe("apiClient session handling", () => {
  const originalApiAdapter = apiClient.defaults.adapter;
  const originalAxiosAdapter = axios.defaults.adapter;
  let refreshCalls = 0;
  let refreshStatus = 200;

  beforeEach(() => {
    refreshCalls = 0;
    refreshStatus = 200;
    // /auth/refresh goes through the bare axios instance.
    axios.defaults.adapter = ((config) => {
      refreshCalls += 1;
      expect(config.withCredentials).toBe(true);
      return respond(config, refreshStatus, refreshStatus === 200 ? session(`fresh-${refreshCalls}`) : { detail: "Session ended" });
    }) as AxiosAdapter;
    apiClient.defaults.adapter = ((config) => {
      const auth = String(config.headers?.Authorization || "");
      return auth.startsWith("Bearer fresh") ? respond(config, 200, { ok: true, auth }) : respond(config, 401, { detail: "expired" });
    }) as AxiosAdapter;
  });

  afterEach(() => {
    apiClient.defaults.adapter = originalApiAdapter;
    axios.defaults.adapter = originalAxiosAdapter;
    setSession(null);
  });

  it("keeps the access token in memory, not in localStorage", () => {
    setSession(session("abc"));
    expect(hasAccessToken()).toBe(true);
    expect(JSON.stringify({ ...localStorage })).not.toContain("abc");
  });

  it("refreshes once for concurrent 401s and retries each request", async () => {
    setSession(session("stale"));

    const results = await Promise.all([apiClient.get("/library/"), apiClient.get("/novel/1")]);

    expect(refreshCalls).toBe(1);
    expect(results.map((result) => result.data.auth)).toEqual(["Bearer fresh-1", "Bearer fresh-1"]);
  });

  it("drops the session when the refresh cookie is rejected", async () => {
    setSession(session("stale"));
    refreshStatus = 401;
    const listener = vi.fn();
    const unsubscribe = onSessionChange(listener);

    await expect(apiClient.get("/library/")).rejects.toMatchObject({ response: { status: 401 } });

    expect(listener).toHaveBeenLastCalledWith(null);
    expect(hasAccessToken()).toBe(false);
    unsubscribe();
  });

  it("does not try to refresh after a failed sign-in", async () => {
    await expect(apiClient.post("/auth/login", { username: "x", password: "y" })).rejects.toBeTruthy();
    expect(refreshCalls).toBe(0);
  });

  it("restores a session from the cookie", async () => {
    expect(await refreshSession()).toMatchObject({ access_token: "fresh-1" });
    expect(hasAccessToken()).toBe(true);
  });
});
