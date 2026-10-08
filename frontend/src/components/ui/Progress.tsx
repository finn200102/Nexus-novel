import { cx } from "./cx";

export interface ProgressProps {
  /** Accessible name, e.g. "Reading progress". */
  label: string;
  /** Current value; omit for an indeterminate bar. */
  value?: number;
  max?: number;
  /** Human text read by screen readers, e.g. "Chapter 41 of 98". Also shown when `showText`. */
  valueText?: string;
  showText?: boolean;
  className?: string;
}

/** 4 px bar: --accent-fill fill, --success when complete (§4.6). */
export function Progress({ label, value, max = 100, valueText, showText, className }: ProgressProps) {
  const indeterminate = value === undefined;
  const clamped = indeterminate ? 0 : Math.min(Math.max(value, 0), max);
  const pct = max > 0 ? (clamped / max) * 100 : 0;
  const complete = !indeterminate && clamped >= max;
  return (
    <div className={cx("ui-progress", complete && "ui-progress--complete", indeterminate && "ui-progress--indeterminate", className)}>
      <div
        role="progressbar"
        aria-label={label}
        aria-valuemin={indeterminate ? undefined : 0}
        aria-valuemax={indeterminate ? undefined : max}
        aria-valuenow={indeterminate ? undefined : clamped}
        aria-valuetext={valueText}
        className="ui-progress__track"
      >
        <div className="ui-progress__fill" style={indeterminate ? undefined : { width: `${pct}%` }} />
      </div>
      {showText && valueText && <span className="ui-progress__text">{valueText}</span>}
    </div>
  );
}
