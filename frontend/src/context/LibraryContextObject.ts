import { createContext } from "react";
import { Library } from "../types/library";

export interface LibraryContextValue {
  libraries: Library[];
  activeLibrary: Library | null;
  activeLibraryId: number | null;
  isLoading: boolean;
  error: string | null;
  refreshLibraries: () => Promise<void>;
  selectLibrary: (libraryId: number) => void;
  createLibrary: (name: string) => Promise<Library | null>;
}

export const LibraryContext = createContext<LibraryContextValue | undefined>(undefined);
