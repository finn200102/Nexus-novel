import type { ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Info, OctagonAlert, X } from "lucide-react";
import { IconButton } from "./IconButton";
import { cx } from "./cx";

export type BannerTone = "info" | "success" | "warning" | "danger";

const ICONS = { info: Info, success: CheckCircle2, warning: AlertTriangle, danger: OctagonAlert };

export interface BannerProps {
  tone?: BannerTone;
  /** One sentence. */
  children: ReactNode;
  /** Optional action (a Button size="sm"). */
  action?: ReactNode;
  onDismiss?: () => void;
  dismissLabel?: string;
  /** Use role="alert" (interrupts) instead of role="status". Only for failures the user must act on. */
  urgent?: boolean;
  className?: string;
}

/** Full-width inline notice at the top of a page: icon + sentence + action (§4.6). */
export function Banner({ tone = "info", children, action, onDismiss, dismissLabel = "Dismiss", urgent, className }: BannerProps) {
  const Icon = ICONS[tone];
  return (
    <div role={urgent ? "alert" : "status"} className={cx("ui-banner", `ui-banner--${tone}`, className)}>
      <Icon className="ui-banner__icon" aria-hidden="true" />
      <div className="ui-banner__text">{children}</div>
      {action && <div className="ui-banner__action">{action}</div>}
      {onDismiss && <IconButton label={dismissLabel} icon={<X />} size="sm" tooltip="none" onClick={onDismiss} />}
    </div>
  );
}
