import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import "./styles/theme.css";
import "./styles/layout.css";
import App from "./App.tsx";
import { AuthProvider } from "./context/AuthContext";
import { LibraryProvider } from "./context/LibraryContext";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AuthProvider>
      <LibraryProvider>
        <App />
      </LibraryProvider>
    </AuthProvider>
  </StrictMode>
);
