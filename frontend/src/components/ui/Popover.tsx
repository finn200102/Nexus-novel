import { useCallback, useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { getFocusable } from "../../hooks/useFocusTrap";
import { useDismiss } from "./useDismiss";
import { cx } from "./cx";

export interface PopoverTriggerProps {
  ref: (node: HTMLButtonElement | null) => void;
  "aria-expanded": boolean;
  "aria-controls": string;
  onClick: () => void;
}

export interface PopoverProps {
  trigger: (props: PopoverTriggerProps) => ReactNode;
  /** Accessible name of the panel. */
  label: string;
  children: ReactNode | ((close: () => void) => ReactNode);
  align?: "start" | "end";
  className?: string;
  /** Controlled open state (optional). */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

/** Non-modal panel anchored to a trigger (filters, quick settings). Escape/outside click close. */
export function Popover({ trigger, label, children, align = "start", className, open: controlled, onOpenChange }: PopoverProps) {
  const [uncontrolled, setUncontrolled] = useState(false);
  const open = controlled ?? uncontrolled;
  const setOpen = useCallback(
    (next: boolean) => {
      if (controlled === undefined) setUncontrolled(next);
      onOpenChange?.(next);
    },
    [controlled, onOpenChange],
  );
  const panelId = `${useId()}-popover`;
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const close = useCallback(() => {
    setOpen(false);
    triggerRef.current?.focus();
  }, [setOpen]);

  const refs = useMemo(() => [panelRef, triggerRef], []);
  const onDismiss = useCallback(
    (reason: "outside" | "escape") => (reason === "escape" ? close() : setOpen(false)),
    [close, setOpen],
  );
  useDismiss(refs, open, onDismiss);

  useEffect(() => {
    if (!open || !panelRef.current) return;
    (getFocusable(panelRef.current)[0] ?? panelRef.current).focus();
  }, [open]);

  return (
    <div className={cx("ui-menu-anchor", className)}>
      {trigger({
        ref: (node) => {
          triggerRef.current = node;
        },
        "aria-expanded": open,
        "aria-controls": panelId,
        onClick: () => setOpen(!open),
      })}
      <div
        ref={panelRef}
        id={panelId}
        role="dialog"
        aria-label={label}
        tabIndex={-1}
        hidden={!open}
        className={cx("ui-popover", `ui-menu--${align}`)}
      >
        {open && (typeof children === "function" ? children(close) : children)}
      </div>
    </div>
  );
}
