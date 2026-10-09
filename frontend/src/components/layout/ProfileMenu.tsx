import { useState } from "react";
import { Link } from "react-router-dom";
import { BarChart3, LogOut, Settings, ShieldCheck } from "lucide-react";
import { Popover } from "../ui";
import { ThemeSwitcher } from "../../theme/ThemeSwitcher";
import { useAuth } from "../../context/AuthContext";
import { initials } from "./navItems";
import { LimitedProfileBadge } from "../household/LimitedProfileNotice";

/** Sidebar profile button: Settings, Admin (admins), Theme, Sign out. */
export function ProfileMenu() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const name = user?.username || "Reader";

  return (
    <Popover
      label="Account"
      className="app-profile"
      open={open}
      onOpenChange={setOpen}
      trigger={(props) => (
        <button type="button" className="app-profile__trigger" {...props}>
          <span className="app-profile__avatar" aria-hidden="true">{initials(name)}</span>
          <span className="app-profile__text">
            <span className="app-profile__name">{name}</span>
            <span className="app-profile__hint">Settings, theme, sign out</span>
          </span>
        </button>
      )}
    >
      <div className="app-profile__panel">
        <p className="app-profile__who">Signed in as <strong>{name}</strong> <LimitedProfileBadge /></p>
        <ul className="app-profile__links">
          <li>
            <Link className="ui-menu__item" to="/settings/account" onClick={() => setOpen(false)}>
              <Settings aria-hidden="true" />
              <span className="ui-menu__label">Settings</span>
            </Link>
          </li>
          <li>
            <Link className="ui-menu__item" to="/stats" onClick={() => setOpen(false)}>
              <BarChart3 aria-hidden="true" />
              <span className="ui-menu__label">Reading stats</span>
            </Link>
          </li>
          {user?.is_admin && (
            <li>
              <Link className="ui-menu__item" to="/admin" onClick={() => setOpen(false)}>
                <ShieldCheck aria-hidden="true" />
                <span className="ui-menu__label">Admin</span>
              </Link>
            </li>
          )}
        </ul>
        <div className="app-profile__theme">
          <p className="app-profile__label" aria-hidden="true">Theme</p>
          <ThemeSwitcher />
        </div>
        <button type="button" className="ui-menu__item" onClick={() => void logout()}>
          <LogOut aria-hidden="true" />
          <span className="ui-menu__label">Sign out</span>
        </button>
      </div>
    </Popover>
  );
}
