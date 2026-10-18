/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useState, useEffect, useRef, ReactNode } from "react";
import { authService, AuthResponse, clearSignedInMarker, readSignedInMarker, RegisterData, SignedInMarker } from "../services/authService";
import { onSessionChange, setSession } from "../services/apiClient";
import { isNetworkError } from "../services/networkErrors";
import { accountIdentity, activateAccountStorage, activeStorageAccount, storageGeneration } from "../services/accountStorage";

interface AuthContextType {
  user: AuthResponse | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  /** Signed in before, but the server cannot be reached right now. */
  isOffline: boolean;
  /** Who was signed in last, while offline. Null when online or signed out. */
  offlineUser: SignedInMarker | null;
  login: (username: string, password: string) => Promise<void>;
  register: (data: RegisterData) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider = ({ children }: { children: ReactNode }) => {
  const [user, setUser] = useState<AuthResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [offlineUser, setOfflineUser] = useState<SignedInMarker | null>(null);
  const preserveSharedMarker = useRef(false);

  useEffect(() => {
    // Signing out in another tab also removes its private in-memory reader
    // state and stops its media, rather than leaving the old account visible.
    const signedOutElsewhere = (event: StorageEvent) => {
      if (event.key !== "nexus-signed-in" && event.key !== null) return;
      const marker = readSignedInMarker();
      if (!marker || event.newValue === null || accountIdentity(marker) !== activeStorageAccount()) {
        // A background tab may receive an old logout after a new sign-in.
        // Clear its memory without deleting the newer shared identity.
        preserveSharedMarker.current = !!marker;
        setSession(null);
        preserveSharedMarker.current = false;
        const generation = storageGeneration();
        if (marker) void authService.restore().catch((error: unknown) => {
          if (generation === storageGeneration() && accountIdentity(readSignedInMarker()) === accountIdentity(marker) && isNetworkError(error)) {
            activateAccountStorage(accountIdentity(marker));
            setOfflineUser(marker);
          }
        });
      }
    };
    window.addEventListener("storage", signedOutElsewhere);
    return () => window.removeEventListener("storage", signedOutElsewhere);
  }, []);

  useEffect(() => {
    // apiClient reports every session change: sign-in, silent refresh, and
    // a refresh the server rejected (signed out elsewhere, disabled, …).
    // Only a rejection (null) ends the session; a fresh session ends offline mode.
    const unsubscribe = onSessionChange((session) => {
      setUser(session);
      setOfflineUser(null);
      if (!session && !preserveSharedMarker.current) clearSignedInMarker();
    });
    authService
      .restore()
      .catch((error: unknown) => {
        // Offline with a previous sign-in: keep the reader usable. A rejected
        // session (401/403) was already reported above and is not kept.
        const marker = readSignedInMarker();
        if (isNetworkError(error) && marker) {
          activateAccountStorage(accountIdentity(marker));
          setOfflineUser(marker);
        }
        return null;
      })
      .finally(() => setIsLoading(false));
    return unsubscribe;
  }, []);

  useEffect(() => {
    if (!offlineUser) return;
    // Back online: renew the session. A network error keeps offline mode.
    const retry = () => {
      authService.restore().catch(() => null);
    };
    window.addEventListener("online", retry);
    return () => window.removeEventListener("online", retry);
  }, [offlineUser]);

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
        isAuthenticated: !!user || !!offlineUser,
        isLoading,
        isOffline: !!offlineUser,
        offlineUser,
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
