import { forwardRef, useId, type InputHTMLAttributes, type ReactNode } from "react";
import { cx } from "./cx";

export interface CheckboxProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type"> {
  label: ReactNode;
  hint?: ReactNode;
}

/** Native checkbox with a clickable label. Use in forms; for immediate settings use Switch. */
export const Checkbox = forwardRef<HTMLInputElement, CheckboxProps>(function Checkbox(
  { label, hint, className, disabled, id, ...rest },
  ref,
) {
  const generated = useId();
  const hintId = hint ? `${id ?? generated}-hint` : undefined;
  return (
    <label className={cx("ui-check", disabled && "ui-check--disabled", className)}>
      <input ref={ref} type="checkbox" id={id} disabled={disabled} aria-describedby={hintId} {...rest} />
      <span className="ui-check__text">
        <span>{label}</span>
        {hint && (
          <span id={hintId} className="ui-check__hint">
            {hint}
          </span>
        )}
      </span>
    </label>
  );
});
