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

  it("treats an empty status-zero refresh as a network failure without replacing the signed-in session",async()=>{
    setSession(session("kept-private-session"));const listener=vi.fn(),unsubscribe=onSessionChange(listener);
    axios.defaults.adapter=((config)=>respond(config,0,"")) as AxiosAdapter;
    await expect(refreshSession()).rejects.toMatchObject({code:"ERR_NETWORK",isAxiosError:true});
    expect(hasAccessToken()).toBe(true);expect(listener).not.toHaveBeenCalled();unsubscribe();
  });
  it("rejects status-zero private API placeholders before adopting empty content",async()=>{
    setSession(session("kept-private-session"));apiClient.defaults.adapter=((config)=>respond(config,0,"")) as AxiosAdapter;
    await expect(apiClient.get("/chapter/content/library/1/42/0")).rejects.toMatchObject({code:"ERR_NETWORK",isAxiosError:true});
    expect(hasAccessToken()).toBe(true);expect(refreshCalls).toBe(0);
  });

  it("restores a session from the cookie", async () => {
    expect(await refreshSession()).toMatchObject({ access_token: "fresh-1" });
    expect(hasAccessToken()).toBe(true);
  });

  it("binds a private write to its original account before another session replaces it", async () => {
    setSession(session("account-a"));
    let config!: InternalAxiosRequestConfig;
    let finish!: (value: unknown) => void;
    apiClient.defaults.adapter = ((request) => {
      config = request;
      return new Promise(done => { finish = done; });
    }) as AxiosAdapter;
    const pending = apiClient.put("/reader/preferences", { values: { typography: { fontSize: 22 } } });
    expect(config.headers.Authorization).toBe("Bearer account-a");
    setSession({ ...session("account-b"), id: 2 });
    finish({ config, status: 200, statusText: "OK", headers: {}, data: { ok: true } });
    await expect(pending).rejects.toMatchObject({ code: "ERR_CANCELED" });
  });

  it("does not retry an old account's queued settings under a different refresh-cookie owner", async () => {
    setSession(session("stale"));
    const attempts: string[] = [];
    apiClient.defaults.adapter = ((config) => {
      attempts.push(String(config.headers.Authorization));
      return attempts.length === 1 ? respond(config, 401, {}) : respond(config, 200, {});
    }) as AxiosAdapter;
    axios.defaults.adapter = ((config) => respond(config, 200, { ...session("fresh-other-account"), id: 2 })) as AxiosAdapter;
    await expect(apiClient.put("/reader/preferences", { values: { typography: { fontSize: 22 } } })).rejects.toBeTruthy();
    expect(attempts).toEqual(["Bearer stale"]);
    expect(hasAccessToken()).toBe(true);
  });

  it("an obsolete refresh cannot replace a newer explicit sign-in", async () => {
    setSession(session("account-a"));
    let finish!: (value: unknown) => void;
    let config!: InternalAxiosRequestConfig;
    axios.defaults.adapter = ((request) => { config = request; return new Promise(done => { finish = done; }); }) as AxiosAdapter;
    const pending = refreshSession();
    await Promise.resolve();
    setSession({ ...session("account-b"), id: 2 });
    finish({ config, status: 200, statusText: "OK", headers: {}, data: session("obsolete-account-a") });
    await expect(pending).rejects.toMatchObject({ code: "ERR_CANCELED" });
    apiClient.defaults.adapter = ((config) => respond(config, 200, { auth: config.headers.Authorization })) as AxiosAdapter;
    expect((await apiClient.get("/reader/preferences")).data.auth).toBe("Bearer account-b");
  });
});
