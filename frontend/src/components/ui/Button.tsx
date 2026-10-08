import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { cx } from "./cx";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ControlSize = "sm" | "md" | "lg";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ControlSize;
  /** Leading icon (Lucide element), 18 px. */
  icon?: ReactNode;
  /** Trailing icon. */
  iconEnd?: ReactNode;
  /** Shows a spinner, keeps the width, sets aria-busy and blocks clicks. */
  loading?: boolean;
  block?: boolean;
}

/** Text button. One primary per view (§4.6). Defaults to type="button". */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", icon, iconEnd, loading = false, block, className, children, type, disabled, onClick, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type ?? "button"}
      className={cx("ui-button", `ui-button--${variant}`, size !== "md" && `ui-button--${size}`, block && "ui-button--block", className)}
      aria-busy={loading || undefined}
      disabled={disabled}
      onClick={loading ? (event) => event.preventDefault() : onClick}
      {...rest}
    >
      {loading && <span className="ui-spinner ui-button__spinner" aria-hidden="true" />}
      <span className="ui-button__label">
        {icon}
        {children}
        {iconEnd}
      </span>
    </button>
  );
});
