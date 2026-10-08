import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { cx } from "./cx";
import type { ControlSize } from "./Button";

export interface IconButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "aria-label" | "children"> {
  /** Required accessible name; also shown as tooltip on hover/focus. */
  label: string;
  icon: ReactNode;
  size?: ControlSize;
  /** Toggle buttons pass their state; renders aria-pressed. */
  pressed?: boolean;
  outlined?: boolean;
  /** Tooltip placement. Default "above". */
  tooltip?: "above" | "below" | "none";
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { label, icon, size = "md", pressed, outlined, tooltip = "above", className, type, ...rest },
  ref,
) {
  if (!label || !label.trim()) {
    throw new Error("IconButton requires a non-empty `label` (its accessible name).");
  }
  return (
    <button
      ref={ref}
      type={type ?? "button"}
      aria-label={label}
      aria-pressed={pressed}
      className={cx(
        "ui-icon-button",
        size !== "md" && `ui-icon-button--${size}`,
        outlined && "ui-icon-button--outlined",
        tooltip === "below" && "ui-icon-button--tip-below",
        className,
      )}
      {...rest}
    >
      {icon}
      {tooltip !== "none" && (
        <span className="ui-tooltip" aria-hidden="true">
          {label}
        </span>
      )}
    </button>
  );
});
