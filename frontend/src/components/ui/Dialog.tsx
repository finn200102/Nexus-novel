import { useId, type ReactNode, type RefObject } from "react";
import { X } from "lucide-react";
import { IconButton } from "./IconButton";
import { ModalLayer } from "./ModalLayer";
import { cx } from "./cx";

export interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  /** One-line description under the title; linked via aria-describedby. */
  description?: ReactNode;
  children?: ReactNode;
  /** Buttons; put the primary action last (right on desktop, stacked on phones). */
  actions?: ReactNode;
  /** Close when the scrim is clicked (default true). */
  closeOnScrim?: boolean;
  initialFocus?: RefObject<HTMLElement | null>;
  className?: string;
  closeLabel?: string;
}

/** Centered modal dialog, max 480 px (§4.6). Name destructive objects in the title. */
export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  actions,
  closeOnScrim = true,
  initialFocus,
  className,
  closeLabel = "Close",
}: DialogProps) {
  const id = useId();
  const titleId = `${id}-title`;
  const descId = description ? `${id}-desc` : undefined;
  return (
    <ModalLayer
      open={open}
      onClose={onClose}
      labelledBy={titleId}
      describedBy={descId}
      closeOnScrim={closeOnScrim}
      initialFocus={initialFocus}
      layerClassName="ui-modal-layer--center"
      panelClassName={cx("ui-dialog", className)}
    >
      <div className="ui-dialog__header">
        <h2 id={titleId} className="ui-dialog__title">
          {title}
        </h2>
        <IconButton label={closeLabel} icon={<X />} size="sm" tooltip="none" onClick={onClose} />
      </div>
      {description && (
        <p id={descId} className="ui-dialog__description">
          {description}
        </p>
      )}
      {children && <div className="ui-dialog__body">{children}</div>}
      {actions && <div className="ui-dialog__actions">{actions}</div>}
    </ModalLayer>
  );
}
