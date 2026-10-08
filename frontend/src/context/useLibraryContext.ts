import { useContext } from "react";
import { LibraryContext } from "./LibraryContextObject";

export const useLibraryContext = () => {
  const context = useContext(LibraryContext);
  if (!context) {
    throw new Error("useLibraryContext must be used within LibraryProvider");
  }
  return context;
};
