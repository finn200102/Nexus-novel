import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { cx } from "./cx";

export interface SwitchProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "onChange" | "children"> {
  checked: boolean;
  onChange: (checked: boolean) => void;
  /** Visible label; without it pass aria-label or aria-labelledby. */
  label?: ReactNode;
  /** Put the label after the track instead of before it. */
  labelAfter?: boolean;
}

/** role="switch" for settings that apply immediately. Space and Enter toggle (native button). */
export const Switch = forwardRef<HTMLButtonElement, SwitchProps>(function Switch(
  { checked, onChange, label, labelAfter, className, type, onClick, ...rest },
  ref,
) {
  const track = (
    <span className="ui-switch__track" aria-hidden="true">
      <span className="ui-switch__thumb" />
    </span>
  );
  return (
    <button
      ref={ref}
      type={type ?? "button"}
      role="switch"
      aria-checked={checked}
      className={cx("ui-switch", className)}
      onClick={(event) => {
        onClick?.(event);
        if (!event.defaultPrevented) onChange(!checked);
      }}
      {...rest}
    >
      {labelAfter && track}
      {label !== undefined && <span className="ui-switch__label">{label}</span>}
      {!labelAfter && track}
    </button>
  );
});
