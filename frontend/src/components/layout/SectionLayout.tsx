import { NavLink, Outlet } from "react-router-dom";

export interface SectionLink {
  label: string;
  to: string;
}

/**
 * Interim sub-navigation for an area (Updates, Settings, Admin) so every old page stays reachable
 * from the new shell. D11–D13 replace it with the designed tabs / sub-nav.
 */
export function SectionLayout({ label, links }: { label: string; links: SectionLink[] }) {
  return (
    <>
      <nav className="app-section-nav" aria-label={label}>
        <ul>
          {links.map((link) => (
            <li key={link.to}>
              <NavLink to={link.to} className="app-section-nav__link">
                {link.label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
      <Outlet />
    </>
  );
}
