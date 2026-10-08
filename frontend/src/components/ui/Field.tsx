import type { ReactNode } from "react";
import { AlertCircle } from "lucide-react";
import { cx } from "./cx";
import { useFieldIds } from "./useFieldIds";

/** Props a Field hands to its control so label, hint and error are wired up. */
export interface FieldControlProps {
  id: string;
  "aria-describedby"?: string;
  "aria-invalid"?: true;
  "aria-required"?: true;
}

export interface FieldProps {
  label: ReactNode;
  hint?: ReactNode;
  /** Error text; makes the control aria-invalid and links the message. */
  error?: ReactNode;
  required?: boolean;
  /** Use a fixed id instead of a generated one. */
  id?: string;
  /** Hide the label visually (still read by screen readers). Prefer visible labels. */
  hideLabel?: boolean;
  className?: string;
  children: (control: FieldControlProps) => ReactNode;
}

/** Label above, hint and error below (§4.6 Input). */
export function Field({ label, hint, error, required, id, hideLabel, className, children }: FieldProps) {
  const { controlId, hintId, errorId } = useFieldIds(id);
  const describedBy = [hint ? hintId : null, error ? errorId : null].filter(Boolean).join(" ") || undefined;
  return (
    <div className={cx("ui-field", className)}>
      <label htmlFor={controlId} className={cx("ui-field__label", hideLabel && "visually-hidden")}>
        {label}
        {required && (
          <span className="ui-field__required" aria-hidden="true">
            *
          </span>
        )}
      </label>
      {children({
        id: controlId,
        "aria-describedby": describedBy,
        "aria-invalid": error ? true : undefined,
        "aria-required": required ? true : undefined,
      })}
      {hint && (
        <p id={hintId} className="ui-field__hint">
          {hint}
        </p>
      )}
      {error && (
        <p id={errorId} className="ui-field__error">
          <AlertCircle aria-hidden="true" />
          <span>{error}</span>
        </p>
      )}
    </div>
  );
}
