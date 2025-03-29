import React from "react";
import {
  BrowserRouter as Router,
  Routes,
  Route,
  useParams,
} from "react-router-dom";
import Layout from "./components/layout/Layout";
import Home from "./pages/Home";
import Signup from "./pages/Signup";
import Login from "./pages/Login";
import LibraryPage from "./pages/Library";
import NovelDetail from "./pages/NovelDetail";
import Reader from "./pages/Reader";

// Wrap individual components with Layout
const WrappedHome = () => (
  <Layout>
    <Home />
  </Layout>
);

const WrappedSignup = () => (
  <Layout>
    <Signup />
  </Layout>
);

const WrappedLogin = () => (
  <Layout>
    <Login />
  </Layout>
);

const App: React.FC = () => {
  return (
    <Router>
      <Routes>
        <Route path="/" element={<WrappedHome />} />
        <Route path="/signup" element={<WrappedSignup />} />
        <Route path="/login" element={<WrappedLogin />} />
        <Route path="/library/:libraryId" element={<LibraryWrapper />} />
        <Route
          path="/library/:libraryId/novels/:novelId"
          element={<NovelWrapper />}
        />
        {/* Updated Route for ChapterReader */}
        <Route
          path="/library/:libraryId/novels/:novelId/:chapterNumber"
          element={<ChapterWrapper />}
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

export default App;
