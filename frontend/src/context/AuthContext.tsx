/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useState, useEffect, ReactNode } from "react";
import { authService, AuthResponse, RegisterData } from "../services/authService";
import { onSessionChange } from "../services/apiClient";

interface AuthContextType {
  user: AuthResponse | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (data: RegisterData) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider = ({ children }: { children: ReactNode }) => {
  const [user, setUser] = useState<AuthResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    // apiClient reports every session change: sign-in, silent refresh, and
    // a refresh the server rejected (signed out elsewhere, disabled, …).
    const unsubscribe = onSessionChange(setUser);
    authService
      .restore()
      .catch(() => null)
      .finally(() => setIsLoading(false));
    return unsubscribe;
  }, []);

  const login = async (username: string, password: string) => {
    await authService.login({ username, password });
  };

  const register = async (data: RegisterData) => {
    await authService.register(data);
  };

  const logout = async () => {
    await authService.logout().catch(() => undefined);
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: !!user,
        isLoading,
        login,
        register,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
};
