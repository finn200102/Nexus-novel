import { forwardRef, type ReactNode, type SelectHTMLAttributes } from "react";
import { ChevronDown } from "lucide-react";
import { Field } from "./Field";
import { cx } from "./cx";

export interface SelectOption {
  value: string;
  label: string;
  disabled?: boolean;
}

export interface SelectProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, "size"> {
  label?: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  hideLabel?: boolean;
  fieldClassName?: string;
  /** Options; alternatively pass <option> children. */
  options?: SelectOption[];
}

/** Native select (keeps platform pickers on phones) with a custom chevron. For rich options use Menu. */
export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { label, hint, error, hideLabel, fieldClassName, options, className, children, required, id, ...rest },
  ref,
) {
  const control = (extra: object) => (
    <div className="ui-select-wrap">
      <select ref={ref} className={cx("ui-select", className)} required={required} id={id} {...rest} {...extra}>
        {options
          ? options.map((option) => (
              <option key={option.value} value={option.value} disabled={option.disabled}>
                {option.label}
              </option>
            ))
          : children}
      </select>
      <ChevronDown className="ui-select-wrap__chevron" aria-hidden="true" />
    </div>
  );
  if (label === undefined) return control({ "aria-invalid": error ? true : undefined });
  return (
    <Field label={label} hint={hint} error={error} required={required} id={id} hideLabel={hideLabel} className={fieldClassName}>
      {(props) => control(props)}
    </Field>
  );
});
