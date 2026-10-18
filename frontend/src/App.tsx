import { Fragment, lazy, Suspense, type ReactNode } from "react";
import { BrowserRouter as Router, Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/layout/Layout";
import ReaderLayout from "./components/layout/ReaderLayout";
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
import AuthorPage from "./pages/AuthorPage";
import FollowingPage from "./pages/FollowingPage";
import Stats from "./pages/Stats";
import Operations from "./pages/Operations";
import ScrapeJobs from "./pages/ScrapeJobs";
import Integrations from "./pages/Integrations";
import StoryGuide from "./pages/StoryGuide";
import StoryGuideReview from "./pages/StoryGuideReview";
import Users from "./pages/Users";
import SourcePlugins from "./pages/admin/SourcePlugins";
import { installPreferenceQueueSync } from "./services/readerPreferenceSync";

installPreferenceQueueSync();
import { AdminLayout } from "./pages/admin/AdminLayout";
import ResetPassword from "./pages/ResetPassword";
import SettingsLayout, { SettingsIndex } from "./pages/settings/SettingsLayout";
import SettingsAccount from "./pages/settings/Account";
import SettingsAppearance from "./pages/settings/Appearance";
import SettingsNotifications from "./pages/settings/Notifications";
import SettingsEReaders from "./pages/settings/EReaders";
import SettingsHidden from "./pages/settings/Hidden";
import SettingsData from "./pages/settings/Data";
import SettingsProviders from "./pages/settings/Providers";
import SettingsVoices from "./pages/settings/Voices";
import SettingsReadingActivity from "./pages/settings/ReadingActivity";
import Recommendations from "./pages/Recommendations";
import Offline from "./pages/Offline";
import More from "./pages/More";
import NotFound from "./pages/NotFound";
import { useAuth } from "./context/AuthContext";

const ProtectedRoute = ({ children }: { children: ReactNode }) => {
  const { isAuthenticated, isLoading, user, offlineUser } = useAuth();
  if (isLoading) return <div className="auth-loading" role="status">Loading Nexus…</div>;
  // A silent refresh can discover an account switch in another tab. Remount
  // private page state (including playing audio), not just its browser stores.
  return isAuthenticated ? <Fragment key={user?.storage_id ?? user?.id ?? offlineUser?.storage_id ?? offlineUser?.id}>{children}</Fragment> : <Navigate to="/login" replace />;
};

/** Static page name for pages that do not call usePageTitle themselves. */
const Titled = ({ title, children }: { title: string; children: ReactNode }) => {
  usePageTitle(title);
  return <>{children}</>;
};


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
        <Route path="for-you" element={<Recommendations />} />
        <Route path="offline" element={<Offline />} />
        <Route path="discover/:site" element={<Discover />} />
        {/* storyId = catalog (metadata) id; library copies join in via /stories/:id (D9). */}
        <Route path="story/:storyId" element={<Story />} />
        <Route path="story/:metadataId/guide" element={<Titled title="AI story guide"><StoryGuide /></Titled>} />
        <Route path="story/:metadataId/guide/review" element={<Titled title="AI story guide review"><StoryGuideReview /></Titled>} />
        <Route path="library" element={<LibraryRoute />} />
        <Route path="library/following" element={<FollowingPage />} />
        <Route path="authors/:authorId" element={<AuthorPage />} />
        {/* Old library story URL: redirects to /story/:catalogId?copy=:novelId. */}
        <Route path="library/:libraryId/novels/:novelId" element={<LibraryStoryRedirect />} />

        <Route path="updates">
          <Route index element={<Updates tab="new" />} />
          <Route path="downloads" element={<Updates tab="downloads" />} />
          <Route path="problems" element={<Updates tab="problems" />} />
        </Route>
        <Route path="stats" element={<Stats />} />
        <Route path="activity" element={<Navigate replace to="/updates" />} />
        <Route path="downloads" element={<Navigate replace to="/updates/downloads" />} />

        <Route path="settings" element={<SettingsLayout />}>
          <Route index element={<SettingsIndex />} />
          <Route path="account" element={<SettingsAccount />} />
          <Route path="appearance" element={<SettingsAppearance />} />
          <Route path="notifications" element={<SettingsNotifications />} />
          <Route path="ereaders" element={<SettingsEReaders />} />
          <Route path="hidden" element={<SettingsHidden />} />
          <Route path="data" element={<SettingsData />} />
          <Route path="providers" element={<SettingsProviders />} />
          <Route path="voices" element={<SettingsVoices />} />
          <Route path="reading" element={<SettingsReadingActivity />} />
          <Route path="*" element={<Navigate replace to="/settings/account" />} />
        </Route>

        <Route path="admin" element={<AdminLayout />}>
          <Route index element={<Navigate replace to="status" />} />
          <Route path="status" element={<Titled title="Status"><Operations /></Titled>} />
          <Route path="plugins" element={<Titled title="Source packages"><SourcePlugins /></Titled>} />
          <Route path="jobs" element={<Titled title="Catalog jobs"><ScrapeJobs /></Titled>} />
          <Route path="users" element={<Titled title="Users & invites"><Users /></Titled>} />
          <Route path="duplicates" element={<Titled title="Catalog review and webhooks"><Integrations /></Titled>} />
          <Route path="webhooks" element={<Titled title="Catalog review and webhooks"><Integrations /></Titled>} />
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
