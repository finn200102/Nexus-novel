import { createContext } from 'react';
import type { ToastMessage, ToastType } from './ToastContext';

export interface ToastContextType {
  toasts: ToastMessage[];
  addToast: (message: string, type?: ToastType, duration?: number) => void;
  removeToast: (id: string) => void;
}

export const ToastContext = createContext<ToastContextType | undefined>(undefined);
