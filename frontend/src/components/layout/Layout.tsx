import React, { useEffect, useState } from "react";
import Navbar from "./Navbar";
import CreateLibraryModal from "../library/CreateLibraryModal";
import SourceStatusBanner from "../common/SourceStatusBanner";

interface LayoutProps {
  children: React.ReactNode;
}

const Layout: React.FC<LayoutProps> = ({ children }) => {
  const [showLibraryModal, setShowLibraryModal] = useState(false);

  useEffect(() => {
    const handler = () => setShowLibraryModal(true);
    window.addEventListener("nexus:create-library", handler);
    return () => window.removeEventListener("nexus:create-library", handler);
  }, []);

  return (
    <div className="layout-shell">
      <Navbar onRequestCreateLibrary={() => setShowLibraryModal(true)} />
      <main className="layout-main">
        <SourceStatusBanner />
        <div className="app-container">
          <div className="app-content">{children}</div>
        </div>
      </main>
      <CreateLibraryModal
        isOpen={showLibraryModal}
        onClose={() => setShowLibraryModal(false)}
      />
    </div>
  );
};

export default Layout;
