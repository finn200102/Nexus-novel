// src/services/apiClient.ts
import axios from "axios";

const apiClient = axios.create({
  // Keep the browser on the same origin. Vite proxies /api in development;
  // nginx proxies it to novel-api in the Compose deployment.
  baseURL: import.meta.env.VITE_API_URL || "/api",
});

// Request interceptor to add the token to every request
apiClient.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem("token");
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// Response interceptor to handle token expiration
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
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
