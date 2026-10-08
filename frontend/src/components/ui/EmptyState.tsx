import type { ReactNode } from "react";
import { cx } from "./cx";

export interface EmptyStateProps {
  /** Lucide icon element; rendered 40 px in --text-muted. */
  icon?: ReactNode;
  /** One sentence heading. */
  title: ReactNode;
  /** One supporting line. */
  description?: ReactNode;
  /** One action. */
  action?: ReactNode;
  /** Heading level to fit the page outline. Default 2. */
  level?: 2 | 3 | 4;
  className?: string;
}

export function EmptyState({ icon, title, description, action, level = 2, className }: EmptyStateProps) {
  const Heading = `h${level}` as "h2" | "h3" | "h4";
  return (
    <div className={cx("ui-empty", className)}>
      {icon && (
        <div className="ui-empty__icon" aria-hidden="true">
          {icon}
        </div>
      )}
      <Heading className="ui-empty__title">{title}</Heading>
      {description && <p className="ui-empty__description">{description}</p>}
      {action && <div className="ui-empty__action">{action}</div>}
    </div>
  );
}
