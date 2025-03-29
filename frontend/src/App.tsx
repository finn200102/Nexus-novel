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

const LibraryWrapper = () => {
  const { libraryId } = useParams<{ libraryId: string }>();

  if (!libraryId) {
    return <div>Invalid library ID</div>;
  }

  return <LibraryPage library_id={parseInt(libraryId, 10)} />;
};

export default App;
