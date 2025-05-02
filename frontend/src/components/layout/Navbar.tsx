import React from "react";
import { Link, useParams, useLocation } from "react-router-dom";

const Navbar: React.FC = () => {
  // Get the library ID from URL parameters if available
  const { libraryId } = useParams<{ libraryId?: string }>();
  const location = useLocation();

  // Determine if we're on a page that has a libraryId
  const hasLibraryContext = libraryId !== undefined;

  // Styling for the navbar
  const navStyle: React.CSSProperties = {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    padding: "1rem 2rem",
    backgroundColor: "#1a1a2e",
    color: "white",
  };

  const linkStyle: React.CSSProperties = {
    color: "white",
    textDecoration: "none",
    marginLeft: "1rem",
    fontWeight: 500,
  };

  const navBrand: React.CSSProperties = {
    fontSize: "1.5rem",
    fontWeight: "bold",
  };

  return (
    <nav style={navStyle}>
      <div style={navBrand}>
        <Link to="/" style={{ ...linkStyle, marginLeft: 0 }}>
          Nexus Novel
        </Link>
      </div>
      <div>
        <Link to="/" style={linkStyle}>
          Home
        </Link>
        <Link to="/signup" style={linkStyle}>
          Signup
        </Link>
        <Link to="/login" style={linkStyle}>
          Login
        </Link>
        {hasLibraryContext && (
          <Link to={`/library/${libraryId}`} style={linkStyle}>
            Library
          </Link>
        )}
        {hasLibraryContext && (
          <Link to={`/library/${libraryId}/discovery`} style={linkStyle}>
            Discovery
          </Link>
        )}
      </div>
    </nav>
  );
};

export default Navbar;
