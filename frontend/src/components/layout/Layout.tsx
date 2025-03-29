import React from "react";
import Navbar from "./Navbar";

interface LayoutProps {
  children: React.ReactNode;
}

const Layout: React.FC<LayoutProps> = ({ children }) => {
  return (
    <div>
      <Navbar />
      <main style={{ padding: "1rem 2rem" }}>{children}</main>
    </div>
  );
};

export default Layout;
