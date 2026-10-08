import { createContext } from 'react';
import type { ToastMessage, ToastOptions, ToastType } from './ToastContext';

export interface ToastContextType {
  toasts: ToastMessage[];
  /** duration in ms; default 5000, errors default to 0 (stay until dismissed). */
  addToast: (message: string, type?: ToastType, duration?: number, options?: ToastOptions) => void;
  removeToast: (id: string) => void;
}

export const ToastContext = createContext<ToastContextType | undefined>(undefined);
