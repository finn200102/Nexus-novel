import { Link, useLocation } from "react-router-dom";
import { Menu as MenuIcon } from "lucide-react";
import { CountBadge, cx } from "../ui";
import { MAIN_NAV, isCurrent, unreadLabel, type MainNavItem } from "./navItems";

const MORE: MainNavItem = { label: "More", to: "/more", icon: MenuIcon, match: ["/more", "/settings", "/admin"] };

/** Phone navigation (< 768 px): five labelled tabs, Updates carries the unread badge. */
export function TabBar({ unreadCount, activePath }: { unreadCount: number;activePath?:string }) {
  const location = useLocation();
  const pathname=activePath??location.pathname;
  return (
    <nav className="app-tabbar" aria-label="Main">
      <ul>
        {[...MAIN_NAV, MORE].map(({ label, to, icon: Icon, match, badge }) => {
          const current = isCurrent(pathname, to, match);
          return (
            <li key={to}>
              <Link to={to} className={cx("app-tab", current && "is-current")} aria-current={current ? "page" : undefined}>
                <span className="app-tab__pill"><Icon aria-hidden="true" /></span>
                <span className="app-tab__label">{label}</span>
                {badge && (
                  <CountBadge className="app-tab__badge" count={unreadCount} label={unreadLabel(unreadCount)} />
                )}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
