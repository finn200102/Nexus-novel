import React from "react";
import { Link, useParams } from "react-router-dom";

const Navbar: React.FC = () => {
  // Get the library ID from URL parameters if available
  const { libraryId } = useParams<{ libraryId?: string }>();

  // Determine if we're on a page that has a libraryId
  const hasLibraryContext = libraryId !== undefined;

  return (
    <nav className="navbar">
      <div className="navbar__brand">
        <Link to="/">Nexus Novel</Link>
      </div>
      <div className="navbar__links">
        <Link to="/">Home</Link>
        {hasLibraryContext && <Link to={`/library/${libraryId}`}>Library</Link>}
        <Link to="/login">Login</Link>
        <Link to="/signup" className="navbar__cta">
          Signup
        </Link>
      </div>
    </nav>
  );
};

export default Navbar;
