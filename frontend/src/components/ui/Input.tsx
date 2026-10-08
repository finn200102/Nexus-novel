import { forwardRef, useRef, type InputHTMLAttributes, type ReactNode } from "react";
import { Search, X } from "lucide-react";
import { Field } from "./Field";
import { IconButton } from "./IconButton";
import { cx } from "./cx";

export interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "size"> {
  /** Visible label. Without it, pass aria-label or wrap in <Field>. */
  label?: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  hideLabel?: boolean;
  fieldClassName?: string;
  /** Search variant: leading icon, type="search" and a clear button when there is a value. */
  search?: boolean;
  /** Called by the clear button (search variant). */
  onClear?: () => void;
  clearLabel?: string;
}

/** Text input; with `label` it renders a full Field (label, hint, error wiring). */
export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { label, hint, error, hideLabel, fieldClassName, search, onClear, clearLabel = "Clear search", className, required, id, ...rest },
  ref,
) {
  const innerRef = useRef<HTMLInputElement | null>(null);
  const setRefs = (node: HTMLInputElement | null) => {
    innerRef.current = node;
    if (typeof ref === "function") ref(node);
    else if (ref) ref.current = node;
  };
  const control = (extra: object) => {
    const input = (
      <input
        ref={setRefs}
        type={search ? "search" : rest.type}
        className={cx("ui-input", className)}
        required={required}
        id={id}
        {...rest}
        {...extra}
      />
    );
    if (!search) return input;
    const hasValue = rest.value !== undefined ? String(rest.value).length > 0 : false;
    return (
      <div className="ui-input-wrap ui-input-wrap--search">
        <Search className="ui-input-wrap__icon" aria-hidden="true" />
        {input}
        {hasValue && onClear && (
          <IconButton
            className="ui-input-wrap__clear"
            size="sm"
            label={clearLabel}
            tooltip="none"
            icon={<X />}
            onClick={() => {
              onClear();
              innerRef.current?.focus();
            }}
          />
        )}
      </div>
    );
  };
  if (label === undefined) return control({ "aria-invalid": error ? true : undefined });
  return (
    <Field label={label} hint={hint} error={error} required={required} id={id} hideLabel={hideLabel} className={fieldClassName}>
      {(props) => control(props)}
    </Field>
  );
});
