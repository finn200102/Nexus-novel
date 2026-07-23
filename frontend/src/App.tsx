import React from "react";
import {
  BrowserRouter as Router,
  Navigate,
  Routes,
  Route,
  useParams,
} from "react-router-dom";
import { ReactNode } from "react";
import Layout from "./components/layout/Layout";
import Home from "./pages/Home";
import Signup from "./pages/Signup";
import Login from "./pages/Login";
import LibraryPage from "./pages/Library";
import NovelDetail from "./pages/NovelDetail";
import Reader from "./pages/Reader";
import Discover from "./pages/Discover";
import DiscoverNovelDetail from "./pages/DiscoverNovelDetail";
import Downloads from "./pages/Downloads";
import Activity from "./pages/Activity";

import { ToastContainer } from "./components/common/Toast";
import { useAuth } from "./context/AuthContext";

// Wrap individual components with Layout
const WrappedHome = () => (
  <Layout>
    <Home />
  </Layout>
);

const WrappedSignup = () => <Signup />;

const WrappedLogin = () => <Login />;

const ProtectedRoute = ({ children }: { children: ReactNode }) => {
  const { isAuthenticated, isLoading } = useAuth();
  if (isLoading) return <div className="auth-loading" role="status">Loading Nexus Novel…</div>;
  return isAuthenticated ? <>{children}</> : <Navigate to="/login" replace />;
};

const Protected = ({ children }: { children: ReactNode }) => (
  <ProtectedRoute>{children}</ProtectedRoute>
);

const App: React.FC = () => {
  return (
    <Router>
      <ToastContainer />
      <Routes>
        <Route path="/" element={<Protected><WrappedHome /></Protected>} />
        <Route path="/signup" element={<WrappedSignup />} />
        <Route path="/login" element={<WrappedLogin />} />
        <Route path="/discover" element={<Protected><WrappedDiscover /></Protected>} />
        <Route path="/discover/:site" element={<Protected><WrappedDiscover /></Protected>} />
        <Route path="/discover/:site/:novelId" element={<Protected><WrappedDiscoverDetail /></Protected>} />
        <Route path="/downloads" element={<Protected><WrappedDownloads /></Protected>} />
        <Route path="/activity" element={<Protected><WrappedActivity /></Protected>} />
        <Route path="/library/:libraryId" element={<Protected><LibraryWrapper /></Protected>} />
        <Route
          path="/library/:libraryId/novels/:novelId"
          element={<Protected><NovelWrapper /></Protected>}
        />
       <Route
          path="/library/:libraryId/novels/:novelId/:chapterNumber"
          element={<Protected><ChapterWrapper /></Protected>}
        />
         </Routes>
    </Router>
  );
};

const NovelWrapper = () => {
  const { libraryId, novelId } = useParams<{
    libraryId: string;
    novelId: string;
  }>();

  if (!libraryId) {
    return <div>Invalid library ID</div>;
  }
  if (!novelId) {
    return <div>Invalid novel ID</div>;
  }

  return (
    <Layout>
      <NovelDetail
        libraryId={parseInt(libraryId, 10)}
        novelId={parseInt(novelId, 10)}
      />
    </Layout>
  );
};

const ChapterWrapper = () => {
  const { libraryId, novelId, chapterNumber } = useParams<{
    libraryId: string;
    novelId: string;
    chapterNumber: string;
  }>();

  if (!libraryId) return <div>Invalid library ID</div>;
  if (!novelId) return <div>Invalid novel ID</div>;
  if (!chapterNumber) return <div>Invalid chapter ID</div>;

  return (
    <Layout>
      <Reader />
    </Layout>
  );
};

const LibraryWrapper = () => {
  const { libraryId } = useParams<{ libraryId: string }>();

  if (!libraryId) {
    return <div>Invalid library ID</div>;
  }

  return (
    <Layout>
      <LibraryPage library_id={parseInt(libraryId, 10)} />
    </Layout>
  );
};

const WrappedDiscover = () => (
  <Layout>
    <Discover />
  </Layout>
);

const WrappedDiscoverDetail = () => (
  <Layout>
    <DiscoverNovelDetail />
  </Layout>
);

const WrappedDownloads = () => (
  <Layout>
    <Downloads />
  </Layout>
);

const WrappedActivity = () => (
  <Layout>
    <Activity />
  </Layout>
);

export default App;
