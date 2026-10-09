import { useState } from "react";
import { Navigate, NavLink, Outlet, useLocation } from "react-router-dom";
import { PageHeader } from "../../components/ui";
import { usePageTitle } from "../../hooks/usePageTitle";
import { SETTINGS_SECTIONS } from "./settingsNav";
import "./settings.css";

const isDesktop = () => typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia("(min-width: 768px)").matches;

/** /settings: desktop opens the first section; phones show the section list on its own. */
export function SettingsIndex() {
  usePageTitle("Settings");
  const [desktop] = useState(isDesktop);
  if (desktop) return <Navigate replace to="/settings/account" />;
  return <PageHeader title="Settings" description="Your account, appearance, notifications, e-readers, hidden content and data." />;
}

/** Desktop: section list beside the content. Phone: list first, then one section at a time (CSS switches on data-view). */
export default function SettingsLayout() {
  const { pathname } = useLocation();
  const view = /^\/settings\/[^/]+/.test(pathname) ? "detail" : "list";
  return (
    <div className="settings-layout" data-view={view}>
      <nav className="settings-nav" aria-label="Settings sections">
        <ul>
          {SETTINGS_SECTIONS.map((section) => (
            <li key={section.to}>
              <NavLink to={section.to} className="settings-nav__link">
                {section.label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
      <div className="settings-content">
        <Outlet />
      </div>
    </div>
  );
}
