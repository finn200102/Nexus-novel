import { useEffect, useRef, type ReactNode, type RefObject } from "react";
import { createPortal } from "react-dom";
import { useFocusTrap } from "../../hooks/useFocusTrap";
import { useInertBackground } from "../../hooks/useInertBackground";
import { cx } from "./cx";

export interface ModalLayerProps {
  open: boolean;
  onClose: () => void;
  /** id of the visible heading that names the dialog. */
  labelledBy?: string;
  /** Accessible name when there is no visible heading. */
  label?: string;
  describedBy?: string;
  /** Close when the scrim is clicked (default true). */
  closeOnScrim?: boolean;
  initialFocus?: RefObject<HTMLElement | null>;
  layerClassName?: string;
  panelClassName?: string;
  children: ReactNode;
}

/**
 * Shared modal behaviour for Dialog and Sheet: portal to <body>, scrim, role="dialog" +
 * aria-modal, focus trap with focus restore, Escape, inert background and scroll lock.
 */
export function ModalLayer({
  open,
  onClose,
  labelledBy,
  label,
  describedBy,
  closeOnScrim = true,
  initialFocus,
  layerClassName,
  panelClassName,
  children,
}: ModalLayerProps) {
  const layerRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useInertBackground(layerRef, open);
  useFocusTrap(panelRef, open, { initialFocus });

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      // Only the topmost layer reacts.
      const layers = document.querySelectorAll(".ui-modal-layer");
      if (layers[layers.length - 1] !== layerRef.current) return;
      event.preventDefault();
      onCloseRef.current();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open]);

  if (!open) return null;
  return createPortal(
    <div ref={layerRef} className={cx("ui-modal-layer", layerClassName)}>
      <div className="ui-scrim" aria-hidden="true" onClick={closeOnScrim ? () => onCloseRef.current() : undefined} />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        aria-label={labelledBy ? undefined : label}
        aria-describedby={describedBy}
        className={panelClassName}
      >
        {children}
      </div>
    </div>,
    document.body,
  );
}
