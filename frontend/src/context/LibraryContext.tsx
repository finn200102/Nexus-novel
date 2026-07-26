import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { libraryService } from "../services/libraryService";
import { Library } from "../types/library";
import { useAuth } from "./AuthContext";

interface LibraryContextValue {
  libraries: Library[];
  activeLibrary: Library | null;
  activeLibraryId: number | null;
  isLoading: boolean;
  error: string | null;
  refreshLibraries: () => Promise<void>;
  selectLibrary: (libraryId: number) => void;
  createLibrary: (name: string) => Promise<Library | null>;
}

const STORAGE_KEY = "nexus.activeLibrary";

const LibraryContext = createContext<LibraryContextValue | undefined>(undefined);

const getStoredLibraryId = (): number | null => {
  if (typeof window === "undefined") {
    return null;
  }
  const storedValue = window.localStorage.getItem(STORAGE_KEY);
  const parsed = storedValue ? Number(storedValue) : null;
  return Number.isFinite(parsed) ? parsed : null;
};

export const LibraryProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const { isAuthenticated, isLoading: authLoading } = useAuth();
  const [libraries, setLibraries] = useState<Library[]>([]);
  const [activeLibraryId, setActiveLibraryId] = useState<number | null>(
    () => getStoredLibraryId()
  );
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const ensureActiveLibrary = useCallback((available: Library[]) => {
    setActiveLibraryId((current) => {
      if (current && available.some((library) => library.id === current)) {
        return current;
      }

      const stored = getStoredLibraryId();
      if (stored && available.some((library) => library.id === stored)) {
        return stored;
      }

      return available.length > 0 ? available[0].id : null;
    });
  }, []);

  const refreshLibraries = useCallback(async () => {
    const token = localStorage.getItem("token");
    if (!token) {
      setLibraries([]);
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    try {
      const response = await libraryService.getLibraries();
      const normalized: Library[] = Array.isArray(response) ? response : [];
      setLibraries(normalized);
      ensureActiveLibrary(normalized);
      setError(null);
    } catch (err) {
      console.error("Failed to load libraries", err);
      setError("Unable to load libraries");
    } finally {
      setIsLoading(false);
    }
  }, [ensureActiveLibrary]);

  useEffect(() => {
    if (authLoading) {
      return;
    }

    if (!isAuthenticated) {
      setLibraries([]);
      setActiveLibraryId(null);
      setError(null);
      setIsLoading(false);
      return;
    }

    void refreshLibraries();
  }, [authLoading, isAuthenticated, refreshLibraries]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    if (activeLibraryId !== null) {
      window.localStorage.setItem(STORAGE_KEY, String(activeLibraryId));
    } else {
      window.localStorage.removeItem(STORAGE_KEY);
    }
  }, [activeLibraryId]);

  const selectLibrary = useCallback((libraryId: number) => {
    setActiveLibraryId(libraryId);
  }, []);

  const createLibrary = useCallback(async (name: string) => {
    try {
      const newLibrary = await libraryService.createLibrary(name);
      if (newLibrary) {
        setLibraries((prev) => [newLibrary, ...prev]);
        setActiveLibraryId(newLibrary.id);
      }
      return newLibrary;
    } catch (err) {
      console.error("Failed to create library", err);
      throw err;
    }
  }, []);

  const activeLibrary = useMemo(() => {
    if (activeLibraryId === null) return null;
    return libraries.find((library) => library.id === activeLibraryId) || null;
  }, [libraries, activeLibraryId]);

  const value = useMemo<LibraryContextValue>(
    () => ({
      libraries,
      activeLibrary,
      activeLibraryId,
      isLoading,
      error,
      refreshLibraries,
      selectLibrary,
      createLibrary,
    }),
    [
      libraries,
      activeLibrary,
      activeLibraryId,
      isLoading,
      error,
      refreshLibraries,
      selectLibrary,
      createLibrary,
    ]
  );

  return (
    <LibraryContext.Provider value={value}>{children}</LibraryContext.Provider>
  );
};

export const useLibraryContext = () => {
  const context = useContext(LibraryContext);
  if (!context) {
    throw new Error("useLibraryContext must be used within LibraryProvider");
  }
  return context;
};
