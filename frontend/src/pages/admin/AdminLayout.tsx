import { NavLink, Outlet } from "react-router-dom";
import { PageHeader } from "../../components/ui";
import "../../styles/admin.css";

/** Admin sections. Old URLs (/operations, /scrape-jobs, /integrations) redirect here via legacyRedirects. */
const ADMIN_SECTIONS = [
  { label: "Status", to: "/admin/status" },
  { label: "Catalog jobs", to: "/admin/jobs" },
  { label: "Users & invites", to: "/admin/users" },
  { label: "Duplicates and webhooks", to: "/admin/duplicates" },
];

/** Shell for every admin page. Owns the single H1 ("Admin"); pages render their sections as H2. */
export function AdminLayout() {
  return (
    <div className="admin-page">
      <PageHeader title="Admin" description="Manage accounts, catalog jobs and server health. Only administrators see this area." />
      <nav className="admin-nav" aria-label="Admin sections">
        <ul>
          {ADMIN_SECTIONS.map((section) => (
            <li key={section.to}>
              <NavLink to={section.to} className="admin-nav__link">
                {section.label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
      <Outlet />
    </div>
  );
}
