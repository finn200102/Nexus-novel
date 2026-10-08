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
}

export const authService = {
  async login(credentials: LoginCredentials): Promise<AuthResponse> {
    const response = await apiClient.post<AuthResponse>("/auth/login", credentials);
    setSession(response.data);
    return response.data;
  },

  async register(data: RegisterData): Promise<AuthResponse> {
    const response = await apiClient.post<AuthResponse>("/auth/signup", data);
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
};
