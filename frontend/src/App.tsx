import React from "react";
import {
  BrowserRouter as Router,
  Routes,
  Route,
  useParams,
} from "react-router-dom";
import Home from "./pages/Home";
import Signup from "./pages/Signup";
import Login from "./pages/Login";
import LibraryPage from "./pages/Library";
import NovelDetail from "./pages/NovelDetail";
import Reader from "./pages/Reader";

const App: React.FC = () => {
  return (
    <Router>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/signup" element={<Signup />} />
        <Route path="/login" element={<Login />} />
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
    <NovelDetail
      libraryId={parseInt(libraryId, 10)}
      novelId={parseInt(novelId, 10)}
    />
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

  return <Reader />;
};

const LibraryWrapper = () => {
  const { libraryId } = useParams<{ libraryId: string }>();

  if (!libraryId) {
    return <div>Invalid library ID</div>;
  }

  return <LibraryPage library_id={parseInt(libraryId, 10)} />;
};

export default App;
