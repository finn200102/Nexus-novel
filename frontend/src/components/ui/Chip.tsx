import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Check, X } from "lucide-react";
import { cx } from "./cx";

export interface FilterChipProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "onChange"> {
  selected: boolean;
  onChange: (selected: boolean) => void;
  children: ReactNode;
}

/** Toggle chip for filters: aria-pressed plus a check icon when selected (never colour alone). */
export function FilterChip({ selected, onChange, children, className, type, onClick, ...rest }: FilterChipProps) {
  return (
    <button
      type={type ?? "button"}
      aria-pressed={selected}
      className={cx("ui-chip", className)}
      onClick={(event) => {
        onClick?.(event);
        if (!event.defaultPrevented) onChange(!selected);
      }}
      {...rest}
    >
      {selected && <Check aria-hidden="true" />}
      {children}
    </button>
  );
}

export interface InputChipProps {
  /** Visible text, e.g. "Fantasy". */
  children: string;
  onRemove: () => void;
  /** Accessible name of the remove button. Default: `Remove ${children}`. */
  removeLabel?: string;
  className?: string;
}

/** Value chip with a remove button ("Remove tag Fantasy"). */
export function InputChip({ children, onRemove, removeLabel, className }: InputChipProps) {
  return (
    <span className={cx("ui-chip ui-chip--input", className)}>
      {children}
      <button type="button" className="ui-chip__remove" aria-label={removeLabel ?? `Remove ${children}`} onClick={onRemove}>
        <X aria-hidden="true" />
      </button>
    </span>
  );
}

export interface ChipProps {
  children: ReactNode;
  icon?: ReactNode;
  className?: string;
}

/** Static chip (tags, metadata). */
export function Chip({ children, icon, className }: ChipProps) {
  return (
    <span className={cx("ui-chip", className)}>
      {icon}
      {children}
    </span>
  );
}
