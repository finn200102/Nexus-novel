import apiClient from "./apiClient";

export interface LoginCredentials {
  username: string;
  password: string;
}

export interface RegisterData {
  username: string;
  password: string;
}

export interface AuthResponse {
  id: number;
  username: string;
  message: string;
  access_token: string;
  token_type: string;
}

export const authService = {
  async login(credentials: LoginCredentials): Promise<AuthResponse> {
    const response = await apiClient.post<AuthResponse>("/auth/login", credentials);
    const { access_token } = response.data;
    localStorage.setItem("token", access_token);
    return response.data;
  },

  async register(data: RegisterData): Promise<AuthResponse> {
    const response = await apiClient.post<AuthResponse>("/auth/signup", data);
    const { access_token } = response.data;
    localStorage.setItem("token", access_token);
    return response.data;
  },

  logout() {
    localStorage.removeItem("token");
    delete apiClient.defaults.headers.common["Authorization"];
    window.location.href = "/login";
  },

  getToken(): string | null {
    return localStorage.getItem("token");
  },

  isAuthenticated(): boolean {
    return !!this.getToken();
  },
};
