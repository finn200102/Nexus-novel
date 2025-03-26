// src/App.tsx
import React, { useState } from "react";
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

const App: React.FC = () => {
  return (
    <Router>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/signup" element={<Signup />} />
        <Route path="/login" element={<Login />} />
        <Route path="/library/:libraryId" element={<LibraryWrapper />}></Route>
      </Routes>
    </Router>
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
