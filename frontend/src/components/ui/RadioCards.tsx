import type { ReactNode } from "react";
import { cx } from "./cx";
import { useRovingRadio } from "./useRovingRadio";

export interface RadioCardOption<T extends string> {
  value: T;
  label: ReactNode;
  description?: ReactNode;
  icon?: ReactNode;
  disabled?: boolean;
}

export interface RadioCardsProps<T extends string> {
  /** Accessible name of the group. */
  label: string;
  options: RadioCardOption<T>[];
  value: T | undefined;
  onChange: (value: T) => void;
  className?: string;
}

/** Larger radio choices with a description (theme previews, download format). Arrow keys move. */
export function RadioCards<T extends string>({ label, options, value, onChange, className }: RadioCardsProps<T>) {
  const disabled = new Set(options.filter((o) => o.disabled).map((o) => o.value));
  const { register, tabStop, onKeyDown } = useRovingRadio(
    options.map((o) => o.value),
    value,
    onChange,
    (v) => disabled.has(v),
  );
  return (
    <div role="radiogroup" aria-label={label} className={cx("ui-radio-cards", className)} onKeyDown={onKeyDown}>
      {options.map((option) => (
        <button
          key={option.value}
          ref={register(option.value)}
          type="button"
          role="radio"
          aria-checked={option.value === value}
          tabIndex={option.value === tabStop ? 0 : -1}
          disabled={option.disabled}
          className="ui-radio-card"
          onClick={() => onChange(option.value)}
        >
          <span className="ui-radio-card__label">
            {option.icon}
            {option.label}
          </span>
          {option.description && <span className="ui-radio-card__desc">{option.description}</span>}
        </button>
      ))}
    </div>
  );
}
