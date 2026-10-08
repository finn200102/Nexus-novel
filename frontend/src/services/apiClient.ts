// src/services/apiClient.ts
import axios, { InternalAxiosRequestConfig } from "axios";

type PendingRequest = {
  controller: AbortController;
  url: string;
};

const pendingRequests = new Map<AbortController, PendingRequest>();

const requestUrl = (config: { baseURL?: string; url?: string }) =>
  `${config.baseURL || ""}${config.url || ""}`;

/** Cancel requests owned by a page before it unmounts or changes context. */
export const cancelPendingRequests = (matches?: string | RegExp) => {
  for (const { controller, url } of pendingRequests.values()) {
    const matchesRequest = !matches || (typeof matches === "string" ? url.includes(matches) : matches.test(url));
    if (matchesRequest) controller.abort();
  }
};

export const isRequestCancelled = (error: unknown) =>
  axios.isCancel(error) || (error instanceof DOMException && error.name === "AbortError");

/** Convert API/transport errors into safe, useful text for users. */
export const getUserFacingError = (error: unknown, fallback: string) => {
  if (isRequestCancelled(error)) return fallback;
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail || error.response?.data?.message;
    if (typeof detail === "string" && detail.trim()) return detail.trim();
    if (error.code === "ECONNABORTED" || error.code === "ETIMEDOUT") return "The request timed out. Please retry.";
    if (!error.response) return "Nexus could not reach the service. Please retry shortly.";
    if (error.response.status === 401) return "Your session expired. Please sign in again.";
    if (error.response.status === 403) return "You do not have permission to perform this action.";
    if (error.response.status >= 500) return "The service is temporarily unavailable. Please retry shortly.";
  }
  return fallback;
};

const API_BASE_URL =
  import.meta.env.VITE_API_URL ||
  // Docker serves the UI and API behind one nginx origin. During local Vite
  // development, use the host-exposed API directly; its CORS policy allows
  // the Vite origin and this avoids proxying back into the frontend server.
  (import.meta.env.DEV ? "http://127.0.0.1:8000" : "/api");

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 15_000,
  // The refresh token is an HttpOnly cookie; the browser must send it.
  withCredentials: true,
});

/** Session data returned by /auth/login, /auth/signup and /auth/refresh. */
export interface SessionResponse {
  id: number;
  username: string;
  message: string;
  access_token: string;
  token_type: string;
  expires_in: number;
  is_admin?: boolean;
}

// The access token lives in memory only. A page load restores it from the
// refresh cookie through /auth/refresh, so nothing readable by scripts is
// persisted.
let accessToken: string | null = null;
let refreshInFlight: Promise<SessionResponse | null> | null = null;
const sessionListeners = new Set<(session: SessionResponse | null) => void>();

export const hasAccessToken = () => accessToken !== null;

/** Store a new session (or null after sign-out) and notify listeners. */
export const setSession = (session: SessionResponse | null) => {
  accessToken = session?.access_token ?? null;
  for (const listener of sessionListeners) listener(session);
};

export const onSessionChange = (listener: (session: SessionResponse | null) => void) => {
  sessionListeners.add(listener);
  return () => {
    sessionListeners.delete(listener);
  };
};

/**
 * Exchange the refresh cookie for a new access token. Concurrent callers
 * share one request: the server rotates the cookie on every use.
 */
export const refreshSession = (): Promise<SessionResponse | null> => {
  if (!refreshInFlight) {
    refreshInFlight = axios
      .post<SessionResponse>(`${API_BASE_URL}/auth/refresh`, null, { withCredentials: true, timeout: 15_000 })
      .then((response) => {
        setSession(response.data);
        return response.data;
      })
      .catch((error) => {
        // Only a rejected cookie ends the session; a network error keeps the
        // current state so an offline reader is not signed out.
        if (axios.isAxiosError(error) && error.response && [401, 403].includes(error.response.status)) {
          setSession(null);
          return null;
        }
        throw error;
      })
      .finally(() => {
        refreshInFlight = null;
      });
  }
  return refreshInFlight;
};

const forgetPending = (signal: unknown) => {
  if (!signal) return;
  for (const [controller, pending] of pendingRequests) {
    if (pending.controller.signal === signal) pendingRequests.delete(controller);
  }
};

apiClient.interceptors.request.use(
  (config) => {
    if (accessToken) {
      config.headers.Authorization = `Bearer ${accessToken}`;
    }
    if (!config.signal) {
      const controller = new AbortController();
      config.signal = controller.signal;
      pendingRequests.set(controller, { controller, url: requestUrl(config) });
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// Requests whose 401 means "wrong credentials", not "session expired".
const AUTH_FORM_REQUEST = /\/auth\/(login|signup|refresh|logout|password-reset)$/;

apiClient.interceptors.response.use(
  (response) => {
    forgetPending(response.config.signal);
    return response;
  },
  async (error) => {
    const config = error.config as (InternalAxiosRequestConfig & { _retried?: boolean }) | undefined;
    forgetPending(config?.signal);
    if (
      config &&
      error.response?.status === 401 &&
      !config._retried &&
      !AUTH_FORM_REQUEST.test(config.url || "")
    ) {
      // The access token expired or its session ended: renew once and retry.
      // If that fails, listeners (AuthContext) drop the user and the
      // protected routes send them to the login page.
      config._retried = true;
      try {
        const session = await refreshSession();
        if (session) {
          config.headers.Authorization = `Bearer ${session.access_token}`;
          return apiClient(config);
        }
      } catch {
        // Fall through to the original error.
      }
    }
    return Promise.reject(error);
  }
);

export default apiClient;
