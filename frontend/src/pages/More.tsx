import { BarChart3, ChevronRight, Download, LogOut, Settings, ShieldCheck } from "lucide-react";
import { Link } from "react-router-dom";
import { PageHeader } from "../components/ui";
import { ThemeSwitcher } from "../theme/ThemeSwitcher";
import { useAuth } from "../context/AuthContext";
import { usePageTitle } from "../hooks/usePageTitle";

/** Phone "More" tab: the rare destinations and account actions the sidebar profile menu holds. */
export default function More() {
  usePageTitle("More");
  const { user, logout } = useAuth();
  const links = [
    { label: "Settings", to: "/settings/account", icon: Settings },
    { label: "Downloads", to: "/updates/downloads", icon: Download },
    { label: "Reading stats", to: "/stats", icon: BarChart3 },
    ...(user?.is_admin ? [{ label: "Admin", to: "/admin", icon: ShieldCheck }] : []),
  ];

  return (
    <div className="more-page">
      <PageHeader title="More" description={user ? `Signed in as ${user.username}` : undefined} />
      <ul className="more-page__list">
        {links.map(({ label, to, icon: Icon }) => (
          <li key={to}>
            <Link className="more-page__item" to={to}>
              <Icon aria-hidden="true" />
              <span>{label}</span>
              <ChevronRight className="more-page__chevron" aria-hidden="true" />
            </Link>
          </li>
        ))}
      </ul>
      <section className="more-page__section" aria-labelledby="more-theme">
        <h2 id="more-theme" className="text-lg">Appearance</h2>
        <ThemeSwitcher />
      </section>
      <button type="button" className="more-page__item more-page__signout" onClick={() => void logout()}>
        <LogOut aria-hidden="true" />
        <span>Sign out</span>
      </button>
    </div>
  );
}
