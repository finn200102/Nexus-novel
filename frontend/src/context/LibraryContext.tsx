import React, {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { libraryService } from "../services/libraryService";
import { hasAccessToken } from "../services/apiClient";
import { Library } from "../types/library";
import { useAuth } from "./AuthContext";
import { LibraryContext, LibraryContextValue } from "./LibraryContextObject";
import { accountStorage, accountIdentity, activeStorageAccount, type AccountIdentity, storageGeneration } from "../services/accountStorage";

const STORAGE_KEY = "nexus.activeLibrary";

const getStoredLibraryId = (): number | null => {
  if (typeof window === "undefined") {
    return null;
  }
  const storedValue = accountStorage.getItem(STORAGE_KEY);
  const parsed = storedValue ? Number(storedValue) : null;
  return Number.isFinite(parsed) ? parsed : null;
};

export const LibraryProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const { isAuthenticated, isLoading: authLoading, user, offlineUser } = useAuth();
  const identity = accountIdentity(user ?? offlineUser);
  const [libraryOwner, setLibraryOwner] = useState<AccountIdentity | null>(null);
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
    const generation = storageGeneration();
    const owner = activeStorageAccount();
    if (!hasAccessToken()) {
      setLibraries([]);
      setLibraryOwner(owner);
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    try {
      const response = await libraryService.getLibraries();
      if (generation !== storageGeneration()) return;
      const normalized: Library[] = Array.isArray(response) ? response : [];
      setLibraries(normalized);
      setLibraryOwner(owner);
      ensureActiveLibrary(normalized);
      setError(null);
    } catch (err) {
      if (generation !== storageGeneration()) return;
      console.error("Failed to load libraries", err);
      setError("Unable to load libraries");
    } finally {
      if (generation === storageGeneration()) setIsLoading(false);
    }
  }, [ensureActiveLibrary]);

  useEffect(() => {
    if (authLoading) {
      return;
    }

    if (!isAuthenticated) {
      setLibraries([]);
      setLibraryOwner(null);
      setActiveLibraryId(null);
      setError(null);
      setIsLoading(false);
      return;
    }

    void refreshLibraries();
  }, [authLoading, isAuthenticated, identity, refreshLibraries]);

  useEffect(() => {
    if (typeof window === "undefined" || libraryOwner !== identity || !hasAccessToken()) {
      return;
    }
    if (activeLibraryId !== null) {
      accountStorage.setItem(STORAGE_KEY, String(activeLibraryId));
    } else {
      accountStorage.removeItem(STORAGE_KEY);
    }
  }, [activeLibraryId, libraryOwner, identity]);

  const selectLibrary = useCallback((libraryId: number) => {
    setActiveLibraryId(libraryId);
  }, []);

  const createLibrary = useCallback(async (name: string) => {
    const generation = storageGeneration();
    try {
      const newLibrary = await libraryService.createLibrary(name);
      if (generation !== storageGeneration()) return null;
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

  const renameLibrary = useCallback(async (libraryId: number, name: string) => {
    const generation = storageGeneration();
    await libraryService.renameLibrary(libraryId, name);
    if (generation !== storageGeneration()) return;
    setLibraries((prev) => prev.map((library) => (library.id === libraryId ? { ...library, name } : library)));
  }, []);

  const deleteLibrary = useCallback(async (libraryId: number) => {
    const generation = storageGeneration();
    await libraryService.deletelibrary(libraryId);
    if (generation !== storageGeneration()) return;
    setLibraries((prev) => {
      const next = prev.filter((library) => library.id !== libraryId);
      setActiveLibraryId((current) => (current === libraryId ? next[0]?.id ?? null : current));
      return next;
    });
  }, []);

  const activeLibrary = useMemo(() => {
    if (activeLibraryId === null) return null;
    return libraries.find((library) => library.id === activeLibraryId) || null;
  }, [libraries, activeLibraryId]);

  const value = useMemo<LibraryContextValue>(
    () => ({
      libraries: libraryOwner === identity ? libraries : [],
      activeLibrary: libraryOwner === identity ? activeLibrary : null,
      activeLibraryId: libraryOwner === identity ? activeLibraryId : null,
      isLoading: libraryOwner !== identity || isLoading,
      error,
      refreshLibraries,
      selectLibrary,
      createLibrary,
      renameLibrary,
      deleteLibrary,
    }),
    [
      libraries,
      libraryOwner,
      identity,
      activeLibrary,
      activeLibraryId,
      isLoading,
      error,
      refreshLibraries,
      selectLibrary,
      createLibrary,
      renameLibrary,
      deleteLibrary,
    ]
  );

  return (
    <LibraryContext.Provider value={value}>{children}</LibraryContext.Provider>
  );
};
