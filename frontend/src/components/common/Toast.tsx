import React, { useEffect, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, Info, OctagonAlert, X } from 'lucide-react';
import { useToast } from '../../context/useToast';
import type { ToastMessage } from '../../context/ToastContext';
import '../../styles/toast.css';

/** At most this many toasts are visible; the rest wait their turn. */
export const MAX_VISIBLE_TOASTS = 3;

const ICONS = { success: CheckCircle2, error: OctagonAlert, info: Info, warning: AlertTriangle };

const ToastItem: React.FC<{ toast: ToastMessage; onDismiss: (id: string) => void }> = ({ toast, onDismiss }) => {
  const [paused, setPaused] = useState(false);
  const remaining = useRef(toast.duration);

  useEffect(() => {
    if (toast.duration <= 0 || paused) return;
    const started = Date.now();
    const timer = window.setTimeout(() => onDismiss(toast.id), remaining.current);
    return () => {
      window.clearTimeout(timer);
      remaining.current -= Date.now() - started;
    };
  }, [paused, toast.duration, toast.id, onDismiss]);

  const Icon = ICONS[toast.type];
  return (
    <div
      className={`toast toast--${toast.type}`}
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setPaused(false);
      }}
    >
      <Icon className="toast__icon" aria-hidden="true" />
      <div className="toast__message">{toast.message}</div>
      {toast.action && (
        <button
          type="button"
          className="toast__action"
          onClick={() => {
            toast.action?.onClick();
            onDismiss(toast.id);
          }}
        >
          {toast.action.label}
        </button>
      )}
      <button type="button" className="toast__close" onClick={() => onDismiss(toast.id)} aria-label="Dismiss notification">
        <X aria-hidden="true" />
      </button>
    </div>
  );
};

/**
 * Toast stack, bottom centre. Two live regions exist from the first render so additions are
 * announced once: errors in role="alert", everything else in role="status" (polite).
 */
export const ToastContainer: React.FC = () => {
  const { toasts, removeToast } = useToast();
  const visible = toasts.slice(0, MAX_VISIBLE_TOASTS);
  const errors = visible.filter((toast) => toast.type === 'error');
  const others = visible.filter((toast) => toast.type !== 'error');

  return (
    <div className="toast-container">
      <div role="alert" className="toast-region">
        {errors.map((toast) => <ToastItem key={toast.id} toast={toast} onDismiss={removeToast} />)}
      </div>
      <div role="status" aria-live="polite" className="toast-region">
        {others.map((toast) => <ToastItem key={toast.id} toast={toast} onDismiss={removeToast} />)}
      </div>
    </div>
  );
};
