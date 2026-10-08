import { forwardRef, type ReactNode, type TextareaHTMLAttributes } from "react";
import { Field } from "./Field";
import { cx } from "./cx";

export interface TextAreaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  hideLabel?: boolean;
  fieldClassName?: string;
}

export const TextArea = forwardRef<HTMLTextAreaElement, TextAreaProps>(function TextArea(
  { label, hint, error, hideLabel, fieldClassName, className, required, id, ...rest },
  ref,
) {
  const control = (extra: object) => (
    <textarea ref={ref} className={cx("ui-textarea", className)} required={required} id={id} {...rest} {...extra} />
  );
  if (label === undefined) return control({ "aria-invalid": error ? true : undefined });
  return (
    <Field label={label} hint={hint} error={error} required={required} id={id} hideLabel={hideLabel} className={fieldClassName}>
      {(props) => control(props)}
    </Field>
  );
});
