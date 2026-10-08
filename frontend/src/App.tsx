import { lazy, Suspense, type ReactNode } from "react";
import { BrowserRouter as Router, Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/layout/Layout";
import ReaderLayout from "./components/layout/ReaderLayout";
import { SectionLayout } from "./components/layout/SectionLayout";
import { LEGACY_REDIRECTS } from "./routes/legacyRedirects";
import { LegacyRedirect } from "./routes/LegacyRedirect";
import { usePageTitle } from "./hooks/usePageTitle";
import Home from "./pages/Home";
import Signup from "./pages/Signup";
import Login from "./pages/Login";
import LibraryRoute from "./pages/LibraryRoute";
import Reader from "./pages/Reader";
import Discover from "./pages/Discover";
import Story, { LibraryStoryRedirect } from "./pages/Story";
import Updates from "./pages/Updates";
import Operations from "./pages/Operations";
import ScrapeJobs from "./pages/ScrapeJobs";
import Integrations from "./pages/Integrations";
import StoryGuide from "./pages/StoryGuide";
import StoryGuideReview from "./pages/StoryGuideReview";
import Users from "./pages/Users";
import Account from "./pages/Account";
import ResetPassword from "./pages/ResetPassword";
import NotificationSettings from "./pages/NotificationSettings";
import HiddenContent from "./pages/HiddenContent";
import More from "./pages/More";
import NotFound from "./pages/NotFound";
import { useAuth } from "./context/AuthContext";

const ProtectedRoute = ({ children }: { children: ReactNode }) => {
  const { isAuthenticated, isLoading } = useAuth();
  if (isLoading) return <div className="auth-loading" role="status">Loading Nexus…</div>;
  return isAuthenticated ? <>{children}</> : <Navigate to="/login" replace />;
};

/** Static page name for pages that do not call usePageTitle themselves. */
const Titled = ({ title, children }: { title: string; children: ReactNode }) => {
  usePageTitle(title);
  return <>{children}</>;
};

const SETTINGS_LINKS = [
  { label: "Account", to: "/settings/account" },
  { label: "Notifications", to: "/settings/notifications" },
  { label: "Hidden content", to: "/settings/hidden" },
];
const ADMIN_LINKS = [
  { label: "Status", to: "/admin/status" },
  { label: "Catalog jobs", to: "/admin/jobs" },
  { label: "Users", to: "/admin/users" },
  { label: "Duplicates and webhooks", to: "/admin/duplicates" },
];

// Dev-only component gallery (/dev/ui); tree-shaken from production builds.
const UiGallery = import.meta.env.DEV ? lazy(() => import("./pages/dev/UiGallery")) : null;

/** Route map (proposal §2.4). Old URLs redirect via LEGACY_REDIRECTS. */
export function AppRoutes() {
  return (
    <Routes>
      <Route path="/signup" element={<Titled title="Create account"><Signup /></Titled>} />
      <Route path="/login" element={<Titled title="Sign in"><Login /></Titled>} />
      <Route path="/reset-password" element={<Titled title="Reset password"><ResetPassword /></Titled>} />
      {LEGACY_REDIRECTS.map(({ from, to }) => (
        <Route key={from} path={from} element={<LegacyRedirect to={to} />} />
      ))}

      <Route element={<ProtectedRoute><Layout /></ProtectedRoute>}>
        <Route index element={<Titled title="Home"><Home /></Titled>} />
        <Route path="discover" element={<Discover />} />
        <Route path="discover/:site" element={<Discover />} />
        {/* storyId = catalog (metadata) id; library copies join in via /stories/:id (D9). */}
        <Route path="story/:storyId" element={<Story />} />
        <Route path="story/:metadataId/guide" element={<Titled title="Story Guide"><StoryGuide /></Titled>} />
        <Route path="story/:metadataId/guide/review" element={<Titled title="Story Guide review"><StoryGuideReview /></Titled>} />
        <Route path="library" element={<LibraryRoute />} />
        {/* Old library story URL: redirects to /story/:catalogId?copy=:novelId. */}
        <Route path="library/:libraryId/novels/:novelId" element={<LibraryStoryRedirect />} />

        <Route path="updates">
          <Route index element={<Updates tab="new" />} />
          <Route path="downloads" element={<Updates tab="downloads" />} />
          <Route path="problems" element={<Updates tab="problems" />} />
        </Route>
        <Route path="activity" element={<Navigate replace to="/updates" />} />
        <Route path="downloads" element={<Navigate replace to="/updates/downloads" />} />

        <Route path="settings" element={<SectionLayout label="Settings sections" links={SETTINGS_LINKS} />}>
          <Route index element={<Navigate replace to="account" />} />
          <Route path="account" element={<Titled title="Account"><Account /></Titled>} />
          <Route path="notifications" element={<Titled title="Notifications"><NotificationSettings /></Titled>} />
          <Route path="hidden" element={<Titled title="Hidden content"><HiddenContent /></Titled>} />
          {/* appearance, reading, devices, data: split out of Account in D12. */}
          <Route path="*" element={<Navigate replace to="/settings/account" />} />
        </Route>

        <Route path="admin" element={<SectionLayout label="Admin sections" links={ADMIN_LINKS} />}>
          <Route index element={<Navigate replace to="status" />} />
          <Route path="status" element={<Titled title="Status"><Operations /></Titled>} />
          <Route path="jobs" element={<Titled title="Catalog jobs"><ScrapeJobs /></Titled>} />
          <Route path="users" element={<Titled title="Users"><Users /></Titled>} />
          <Route path="duplicates" element={<Titled title="Duplicates and webhooks"><Integrations /></Titled>} />
          <Route path="webhooks" element={<Titled title="Duplicates and webhooks"><Integrations /></Titled>} />
        </Route>

        <Route path="more" element={<More />} />
        <Route path="*" element={<NotFound />} />
      </Route>

      {/* Reader: full screen, no app shell. Moves to /read/:storyId/:chapter with D5/D9. */}
      <Route element={<ProtectedRoute><ReaderLayout /></ProtectedRoute>}>
        <Route path="/library/:libraryId/novels/:novelId/:chapterNumber" element={<Reader />} />
      </Route>

      {UiGallery && (
        <Route path="/dev/ui" element={<Suspense fallback={null}><Titled title="UI primitives"><UiGallery /></Titled></Suspense>} />
      )}
    </Routes>
  );
}

const App = () => (
  <Router>
    <AppRoutes />
  </Router>
);

export default App;
