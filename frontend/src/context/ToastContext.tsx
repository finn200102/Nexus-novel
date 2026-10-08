import React, { useState, useCallback, useMemo, ReactNode } from 'react';

import { ToastContext } from './ToastContextObject';

export type ToastType = 'success' | 'error' | 'info' | 'warning';

export interface ToastAction {
  label: string;
  onClick: () => void;
}

export interface ToastMessage {
  id: string;
  message: string;
  type: ToastType;
  /** Auto-dismiss after this many ms; 0 = stays until dismissed. */
  duration: number;
  action?: ToastAction;
}

export interface ToastOptions {
  action?: ToastAction;
}

/** Default lifetime (§4.6): 5 s; errors stay until dismissed. */
export const DEFAULT_TOAST_MS = 5000;

let toastIdCounter = 0;

export const ToastProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((toast) => toast.id !== id));
  }, []);

  const addToast = useCallback((message: string, type: ToastType = 'info', duration?: number, options?: ToastOptions) => {
    const id = `toast-${toastIdCounter++}`;
    const lifetime = duration ?? (type === 'error' ? 0 : DEFAULT_TOAST_MS);
    setToasts((prev) => {
      // The same message twice in a row is not shown twice.
      if (prev.some((toast) => toast.message === message && toast.type === type)) return prev;
      return [...prev, { id, message, type, duration: lifetime, action: options?.action }];
    });
  }, []);

  const value = useMemo(() => ({ toasts, addToast, removeToast }), [toasts, addToast, removeToast]);
  return <ToastContext.Provider value={value}>{children}</ToastContext.Provider>;
};
