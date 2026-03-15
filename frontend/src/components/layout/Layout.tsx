import React from "react";
import Navbar from "./Navbar";

interface LayoutProps {
  children: React.ReactNode;
}

const Layout: React.FC<LayoutProps> = ({ children }) => {
  return (
    <div className="layout-shell">
      <Navbar />
      <main className="layout-main">
        <div className="app-container">
          <div className="app-content">{children}</div>
        </div>
      </main>
    </div>
  );
};

export default Layout;
