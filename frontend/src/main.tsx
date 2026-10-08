import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource-variable/inter";
import "./styles/tokens.css";
import "./styles/base.css";
import "./index.css";
import "./styles/layout.css";
import App from "./App.tsx";
import { ToastContainer } from "./components/common/Toast";
import { AuthProvider } from "./context/AuthContext";
import { LibraryProvider } from "./context/LibraryContext";
import { ToastProvider } from "./context/ToastContext";
import { ThemeProvider } from "./theme/ThemeProvider";

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => undefined));
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider>
    <AuthProvider>
      <LibraryProvider>
      <ToastProvider>
          <ToastContainer />
          <App />
        </ToastProvider>
      </LibraryProvider>
    </AuthProvider>
    </ThemeProvider>
  </StrictMode>
);
