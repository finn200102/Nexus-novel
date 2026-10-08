import type { HTMLAttributes, ReactNode } from "react";
import { cx } from "./cx";

export interface CardProps extends HTMLAttributes<HTMLElement> {
  as?: "div" | "article" | "section" | "li";
  media?: ReactNode;
  header?: ReactNode;
  footer?: ReactNode;
  /** Padding: "md" 16 px (default), "lg" 24 px, "none". */
  padding?: "none" | "md" | "lg";
  /** Hover style for cards with a stretched link (put `ui-stretched-link` on the title link). */
  interactive?: boolean;
}

/** Flat surface card (§4.6). Never nest cards; use dividers inside. */
export function Card({ as: Tag = "div", media, header, footer, padding = "md", interactive, className, children, ...rest }: CardProps) {
  return (
    <Tag className={cx("ui-card", `ui-card--pad-${padding}`, interactive && "ui-card--interactive", className)} {...rest}>
      {media && <div className="ui-card__media">{media}</div>}
      {header && <div className="ui-card__header">{header}</div>}
      {children !== undefined && <div className="ui-card__body">{children}</div>}
      {footer && <div className="ui-card__footer">{footer}</div>}
    </Tag>
  );
}
