import { Link, useLocation } from "react-router-dom";
import { BookOpen, ShieldCheck } from "lucide-react";
import { CountBadge, cx } from "../ui";
import { useAuth } from "../../context/AuthContext";
import { MAIN_NAV, isCurrent, unreadLabel } from "./navItems";
import { ProfileMenu } from "./ProfileMenu";

/** Desktop navigation (≥ 768 px): full sidebar from 1280 px, labelled icon rail below. */
export function Sidebar({ unreadCount, activePath }: { unreadCount: number;activePath?:string }) {
  const location = useLocation();
  const pathname=activePath??location.pathname;
  const { user } = useAuth();
  const adminCurrent = isCurrent(pathname, "/admin", ["/admin"]);

  return (
    <nav className="app-sidebar" aria-label="Main">
      <Link to="/" className="app-sidebar__brand">
        <span className="app-sidebar__mark" aria-hidden="true"><BookOpen /></span>
        <span className="app-sidebar__brand-text">Nexus</span>
      </Link>
      <ul className="app-sidebar__list">
        {MAIN_NAV.map(({ label, to, icon: Icon, match, badge }) => {
          const current = isCurrent(pathname, to, match);
          return (
            <li key={to}>
              <Link to={to} className={cx("app-nav-link", current && "is-current")} aria-current={current ? "page" : undefined}>
                <span className="app-nav-link__icon"><Icon aria-hidden="true" /></span>
                <span className="app-nav-link__label">{label}</span>
                {badge && <CountBadge className="app-nav-link__badge" count={unreadCount} label={unreadLabel(unreadCount)} />}
              </Link>
            </li>
          );
        })}
      </ul>
      {user?.is_admin && (
        <>
          <hr className="app-sidebar__divider" />
          <ul className="app-sidebar__list">
            <li>
              <Link to="/admin" className={cx("app-nav-link", adminCurrent && "is-current")} aria-current={adminCurrent ? "page" : undefined}>
                <span className="app-nav-link__icon"><ShieldCheck aria-hidden="true" /></span>
                <span className="app-nav-link__label">Admin</span>
              </Link>
            </li>
          </ul>
        </>
      )}
      <div className="app-sidebar__bottom">
        <ProfileMenu />
      </div>
    </nav>
  );
}
