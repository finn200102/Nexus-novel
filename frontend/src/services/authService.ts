import apiClient, { refreshSession, SessionResponse, setSession } from "./apiClient";

export interface LoginCredentials {
  username: string;
  password: string;
}

export interface RegisterData {
  username: string;
  password: string;
  invite_code?: string;
}

export type AuthResponse = SessionResponse;

export type SignupMode = "open" | "invite" | "closed";

export interface SignupConfig {
  signup_mode: SignupMode;
  /** No account exists yet: the first sign-up becomes the administrator. */
  first_user: boolean;
  /** False when the instance only allows single sign-on. */
  password_login?: boolean;
  /** Present when single sign-on (OpenID Connect) is configured. */
  oidc?: { display_name: string } | null;
}

export interface LinkedSignInStatus {
  enabled: boolean;
  display_name: string;
  linked: boolean;
  has_password: boolean;
  password_login: boolean;
}

/**
 * Non-secret record that this browser was signed in, so an offline reload can
 * keep the reader open. It holds no tokens; the server still decides access.
 */
export interface SignedInMarker {
  username: string;
  is_admin: boolean;
}

const SIGNED_IN_MARKER_KEY = "nexus-signed-in";

export const readSignedInMarker = (): SignedInMarker | null => {
  try {
    const parsed = JSON.parse(localStorage.getItem(SIGNED_IN_MARKER_KEY) || "null") as SignedInMarker | null;
    return parsed && typeof parsed.username === "string" ? { username: parsed.username, is_admin: !!parsed.is_admin } : null;
  } catch {
    return null;
  }
};

export const writeSignedInMarker = (session: { username: string; is_admin?: boolean }) => {
  try {
    localStorage.setItem(SIGNED_IN_MARKER_KEY, JSON.stringify({ username: session.username, is_admin: !!session.is_admin }));
  } catch {
    // Storage may be blocked; the user then simply sees the login page offline.
  }
};

export const clearSignedInMarker = () => {
  try {
    localStorage.removeItem(SIGNED_IN_MARKER_KEY);
  } catch {
    // Nothing to clear when storage is unavailable.
  }
};

export const authService = {
  async login(credentials: LoginCredentials): Promise<AuthResponse> {
    const response = await apiClient.post<AuthResponse>("/auth/login", credentials);
    writeSignedInMarker(response.data);
    setSession(response.data);
    return response.data;
  },

  async register(data: RegisterData): Promise<AuthResponse> {
    const response = await apiClient.post<AuthResponse>("/auth/signup", data);
    writeSignedInMarker(response.data);
    setSession(response.data);
    return response.data;
  },

  /** Restore the session from the refresh cookie, e.g. after a page load. */
  restore(): Promise<AuthResponse | null> {
    return refreshSession();
  },

  async logout(): Promise<void> {
    try {
      await apiClient.post("/auth/logout");
    } finally {
      clearSignedInMarker();
      setSession(null);
    }
  },

  async logoutOtherDevices(): Promise<number> {
    const response = await apiClient.post<{ revoked_sessions: number }>("/auth/logout-others");
    return response.data.revoked_sessions;
  },

  async changePassword(currentPassword: string, newPassword: string): Promise<void> {
    await apiClient.post("/auth/password", { current_password: currentPassword, new_password: newPassword });
  },

  async resetPassword(token: string, newPassword: string): Promise<void> {
    await apiClient.post("/auth/password-reset", { token, new_password: newPassword });
  },

  async signupConfig(): Promise<SignupConfig> {
    const response = await apiClient.get<SignupConfig>("/auth/config");
    return response.data;
  },

  /** Full-page navigation target that starts single sign-on. */
  singleSignOnUrl(): string {
    return `${apiClient.defaults.baseURL ?? ""}/auth/oidc/login`;
  },

  async linkedSignIn(): Promise<LinkedSignInStatus> {
    const response = await apiClient.get<LinkedSignInStatus>("/auth/oidc/status");
    return response.data;
  },

  /** Returns the provider URL to visit; the callback links this account. */
  async startLinkingSignIn(): Promise<string> {
    const response = await apiClient.post<{ authorization_url: string }>("/auth/oidc/link");
    return response.data.authorization_url;
  },

  async unlinkSignIn(): Promise<void> {
    await apiClient.delete("/auth/oidc/link");
  },
};
