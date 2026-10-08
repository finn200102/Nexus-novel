import type { HTMLAttributes, ReactNode } from "react";
import { cx } from "./cx";

export type Tone = "neutral" | "accent" | "info" | "success" | "warning" | "danger";

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: Tone;
  icon?: ReactNode;
  children: ReactNode;
}

/** 20 px pill, always with text (§4.6). */
export function Badge({ tone = "neutral", icon, children, className, ...rest }: BadgeProps) {
  return (
    <span className={cx("ui-badge", `ui-badge--${tone}`, className)} {...rest}>
      {icon}
      {children}
    </span>
  );
}

export interface CountBadgeProps extends HTMLAttributes<HTMLSpanElement> {
  count: number;
  /** Accessible text, e.g. "3 stories with new chapters". The number alone is aria-hidden. */
  label: string;
  max?: number;
}

/** Numeric badge for nav items; screen readers get `label` instead of the bare number. */
export function CountBadge({ count, label, max = 99, className, ...rest }: CountBadgeProps) {
  if (count <= 0) return null;
  return (
    <span className={cx("ui-badge ui-badge--count", className)} {...rest}>
      <span aria-hidden="true">{count > max ? `${max}+` : count}</span>
      <span className="visually-hidden">{label}</span>
    </span>
  );
}
