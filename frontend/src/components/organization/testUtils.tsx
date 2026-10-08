import React from "react";
import { render } from "@testing-library/react";
import { vi } from "vitest";
import { ToastContext } from "../../context/ToastContextObject";
import type { ToastContextType } from "../../context/ToastContextObject";

/** Renders with a stub toast context so components can call useToast(). */
export const renderWithToasts = (ui: React.ReactElement, addToast = vi.fn()) => {
  const toast: ToastContextType = { toasts: [], addToast, removeToast: vi.fn() };
  return { addToast, ...render(<ToastContext.Provider value={toast}>{ui}</ToastContext.Provider>) };
};
