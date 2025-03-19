import React from "react";
import CreateLibraryForm from "../components/library/CreateLibraryForm";
import LibraryList from "../components/library/LibraryList";

const LibraryPage: React.FC = () => {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        height: "100vh",
      }}
    >
      <h1>Lib</h1>
      <CreateLibraryForm />
      <h2>Libs</h2>
      <LibraryList />
    </div>
  );
};

export default LibraryPage;
