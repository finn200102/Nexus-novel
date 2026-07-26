// src/services/apiClient.ts
import axios from "axios";

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

const apiClient = axios.create({
  // Docker serves the UI and API behind one nginx origin. During local Vite
  // development, use the host-exposed API directly; its CORS policy allows
  // the Vite origin and this avoids proxying back into the frontend server.
  baseURL:
    import.meta.env.VITE_API_URL ||
    (import.meta.env.DEV ? "http://127.0.0.1:8000" : "/api"),
  timeout: 15_000,
});

// Request interceptor to add the token to every request
apiClient.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem("token");
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
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

// Response interceptor to handle token expiration
apiClient.interceptors.response.use(
  (response) => {
    for (const [controller, pending] of pendingRequests) {
      if (pending.controller.signal === response.config.signal) pendingRequests.delete(controller);
    }
    return response;
  },
  (error) => {
    if (error.config?.signal) {
      for (const [controller, pending] of pendingRequests) {
        if (pending.controller.signal === error.config.signal) pendingRequests.delete(controller);
      }
    }
    if (error.response && error.response.status === 401) {
      // Token expired or invalid
      localStorage.removeItem("token");
      // Redirect to login
      window.location.href = "/login";
    }
    return Promise.reject(error);
  }
);

export default apiClient;
