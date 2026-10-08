import { forwardRef, type ReactNode } from "react";
import { cx } from "./cx";

export interface PageHeaderProps {
  title: ReactNode;
  /** One line under the title. */
  description?: ReactNode;
  /** Actions on the right; wrap under the title on phones. */
  actions?: ReactNode;
  /** Content above the title (e.g. a back link). No eyebrows. */
  before?: ReactNode;
  className?: string;
}

/**
 * Page H1 + description + actions. The H1 has tabIndex=-1 so route-change focus
 * management (D4) can move focus to it; forward a ref to reach it.
 */
export const PageHeader = forwardRef<HTMLHeadingElement, PageHeaderProps>(function PageHeader(
  { title, description, actions, before, className },
  ref,
) {
  return (
    <header className={cx("ui-page-header", className)}>
      {before && <div className="ui-page-header__before">{before}</div>}
      <div className="ui-page-header__main">
        <div className="ui-page-header__text">
          <h1 ref={ref} tabIndex={-1} className="ui-page-header__title">
            {title}
          </h1>
          {description && <p className="ui-page-header__description">{description}</p>}
        </div>
        {actions && <div className="ui-page-header__actions">{actions}</div>}
      </div>
    </header>
  );
});
