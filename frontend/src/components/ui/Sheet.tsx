import { useId, type ReactNode, type RefObject } from "react";
import { X } from "lucide-react";
import { IconButton } from "./IconButton";
import { ModalLayer } from "./ModalLayer";
import { cx } from "./cx";

export type SheetVariant = "auto" | "bottom" | "side";

export interface SheetProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  /** Hide the visible title (it still names the sheet). */
  hideTitle?: boolean;
  children: ReactNode;
  /** Sticky footer (actions). */
  footer?: ReactNode;
  /**
   * "bottom": bottom sheet; "side": side drawer (360–400 px);
   * "auto" (default): bottom sheet under 768 px, side drawer above.
   */
  variant?: SheetVariant;
  /** Side of the drawer. Default "right". */
  side?: "left" | "right";
  initialFocus?: RefObject<HTMLElement | null>;
  className?: string;
  closeLabel?: string;
}

/** Bottom sheet (phones) / side drawer (desktop): modal, trapped, Escape and scrim close. */
export function Sheet({
  open,
  onClose,
  title,
  hideTitle,
  children,
  footer,
  variant = "auto",
  side = "right",
  initialFocus,
  className,
  closeLabel = "Close",
}: SheetProps) {
  const titleId = `${useId()}-title`;
  return (
    <ModalLayer
      open={open}
      onClose={onClose}
      labelledBy={titleId}
      initialFocus={initialFocus}
      layerClassName={cx("ui-modal-layer--sheet", `ui-modal-layer--${variant}`, `ui-modal-layer--${side}`)}
      panelClassName={cx("ui-sheet", `ui-sheet--${variant}`, `ui-sheet--${side}`, className)}
    >
      <div className="ui-sheet__handle" aria-hidden="true" />
      <div className="ui-sheet__header">
        <h2 id={titleId} className={cx("ui-sheet__title", hideTitle && "visually-hidden")}>
          {title}
        </h2>
        <IconButton label={closeLabel} icon={<X />} tooltip="none" onClick={onClose} />
      </div>
      <div className="ui-sheet__body">{children}</div>
      {footer && <div className="ui-sheet__footer">{footer}</div>}
    </ModalLayer>
  );
}
