import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import "./styles/theme.css";
import "./styles/layout.css";
import App from "./App.tsx";
import { AuthProvider } from "./context/AuthContext";
import { LibraryProvider } from "./context/LibraryContext";
import { ToastProvider } from "./context/ToastContext";

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => undefined));
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AuthProvider>
      <LibraryProvider>
        <ToastProvider>
          <App />
        </ToastProvider>
      </LibraryProvider>
    </AuthProvider>
  </StrictMode>
);
