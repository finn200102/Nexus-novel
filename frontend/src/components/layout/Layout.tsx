import React, { useState } from "react";
import Navbar from "./Navbar";
import CreateLibraryModal from "../library/CreateLibraryModal";

interface LayoutProps {
  children: React.ReactNode;
}

const Layout: React.FC<LayoutProps> = ({ children }) => {
  const [showLibraryModal, setShowLibraryModal] = useState(false);

  return (
    <div className="layout-shell">
      <Navbar onRequestCreateLibrary={() => setShowLibraryModal(true)} />
      <main className="layout-main">
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
