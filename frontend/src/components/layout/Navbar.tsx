import React from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import LibrarySwitcher from "./LibrarySwitcher";
import { useLibraryContext } from "../../context/LibraryContext";
import { useAuth } from "../../context/AuthContext";

interface NavbarProps {
  onRequestCreateLibrary?: () => void;
}

const Navbar: React.FC<NavbarProps> = ({ onRequestCreateLibrary }) => {
  const navigate = useNavigate();
  const location = useLocation();
  const { activeLibrary } = useLibraryContext();
  const { isAuthenticated, user, logout } = useAuth();

  const goToActiveLibrary = () => {
    if (!activeLibrary) return;
    navigate(`/library/${activeLibrary.id}`);
  };

  const triggerAddNovel = () => {
    if (!activeLibrary) return;
    window.dispatchEvent(
      new CustomEvent("nexus:add-novel", {
        detail: { libraryId: activeLibrary.id },
      })
    );
    navigate(`/library/${activeLibrary.id}`);
  };

  return (
    <nav className="navbar">
      <div className="navbar__left">
        <Link to="/" className="navbar__brand">
          Nexus Novel
        </Link>
        <div className="navbar__nav">
          <Link
            to="/"
            className={location.pathname === "/" ? "is-active" : ""}
          >
            Dashboard
          </Link>
          <Link
            to="/discover/royalroad"
            className={location.pathname.startsWith("/discover") ? "is-active" : ""}
          >
            Discover
          </Link>
          <Link
            to="/downloads"
            className={location.pathname === "/downloads" ? "is-active" : ""}
          >
            Downloads
          </Link>
          <button
            type="button"
            className="navbar__ghost-btn"
            onClick={goToActiveLibrary}
            disabled={!activeLibrary}
          >
            Library View
          </button>
        </div>
      </div>

      <div className="navbar__center">
        <LibrarySwitcher onCreateLibrary={onRequestCreateLibrary} />
      </div>

      <div className="navbar__right">
        {onRequestCreateLibrary && (
          <button
            type="button"
            className="navbar__ghost-btn"
            onClick={onRequestCreateLibrary}
          >
            New Library
          </button>
        )}
        <button
          type="button"
          className="navbar__action"
          onClick={triggerAddNovel}
          disabled={!activeLibrary}
        >
          Add Novel
        </button>
        {isAuthenticated ? (
          <div className="navbar__user">
            <span className="navbar__user-name">
              {user?.username || "Reader"}
            </span>
            <button type="button" onClick={logout} className="navbar__ghost-btn">
              Logout
            </button>
          </div>
        ) : (
          <div className="navbar__auth-links">
            <Link to="/login">Login</Link>
            <Link to="/signup" className="navbar__cta">
              Sign up
            </Link>
          </div>
        )}
      </div>
    </nav>
  );
};

export default Navbar;
