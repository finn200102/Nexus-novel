import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { cx } from "./cx";

export interface ListRowProps {
  title: ReactNode;
  meta?: ReactNode;
  /** Leading media: Cover size 48, avatar or icon. */
  media?: ReactNode;
  /** Trailing actions; stay separately focusable above the row link. */
  actions?: ReactNode;
  /** Makes the whole row a link (stretched link on the title). */
  to?: string;
  onClick?: () => void;
  selected?: boolean;
  /** Element for the row (li inside a ul/ol). Default "div". */
  as?: "div" | "li";
  className?: string;
}

/** 56 px row (72 with media): media, title + meta, trailing actions (§4.6). */
export function ListRow({ title, meta, media, actions, to, onClick, selected, as: Tag = "div", className }: ListRowProps) {
  const titleNode = to ? (
    <Link to={to} className="ui-list-row__title ui-stretched-link">
      {title}
    </Link>
  ) : onClick ? (
    <button type="button" className="ui-list-row__title ui-stretched-link" onClick={onClick}>
      {title}
    </button>
  ) : (
    <span className="ui-list-row__title">{title}</span>
  );
  return (
    <Tag
      className={cx("ui-list-row", media !== undefined && "ui-list-row--media", (to || onClick) && "ui-list-row--interactive", selected && "ui-list-row--selected", className)}
      aria-current={selected ? "true" : undefined}
    >
      {media && <div className="ui-list-row__media">{media}</div>}
      <div className="ui-list-row__text">
        {titleNode}
        {meta && <div className="ui-list-row__meta">{meta}</div>}
      </div>
      {actions && <div className="ui-list-row__actions">{actions}</div>}
    </Tag>
  );
}
