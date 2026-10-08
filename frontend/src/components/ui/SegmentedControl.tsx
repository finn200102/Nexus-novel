import type { ReactNode } from "react";
import { cx } from "./cx";
import { useRovingRadio } from "./useRovingRadio";

export interface SegmentedOption<T extends string> {
  value: T;
  label: ReactNode;
  icon?: ReactNode;
  /** Accessible name when the label is icon-only. */
  ariaLabel?: string;
  disabled?: boolean;
}

export interface SegmentedControlProps<T extends string> {
  /** Accessible name of the group (e.g. "Theme"). */
  label: string;
  options: SegmentedOption<T>[];
  value: T;
  onChange: (value: T) => void;
  block?: boolean;
  className?: string;
}

/** 2–4 mutually exclusive options (Scroll/Pages, Grid/List, theme). role="radiogroup" with arrow keys. */
export function SegmentedControl<T extends string>({ label, options, value, onChange, block, className }: SegmentedControlProps<T>) {
  const disabled = new Set(options.filter((o) => o.disabled).map((o) => o.value));
  const { register, tabStop, onKeyDown } = useRovingRadio(
    options.map((o) => o.value),
    value,
    onChange,
    (v) => disabled.has(v),
  );
  return (
    <div role="radiogroup" aria-label={label} className={cx("ui-segmented", block && "ui-segmented--block", className)} onKeyDown={onKeyDown}>
      {options.map((option) => (
        <button
          key={option.value}
          ref={register(option.value)}
          type="button"
          role="radio"
          aria-checked={option.value === value}
          aria-label={option.ariaLabel}
          tabIndex={option.value === tabStop ? 0 : -1}
          disabled={option.disabled}
          className="ui-segmented__option"
          onClick={() => onChange(option.value)}
        >
          {option.icon}
          {option.label}
        </button>
      ))}
    </div>
  );
}
