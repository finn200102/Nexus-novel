import React from "react";
import CreateLibraryForm from "../components/library/CreateLibraryForm";
import LibraryList from "../components/library/LibraryList";

const Home: React.FC = () => {
  return (
    <div>
      <h1>Welcome to the Home Page</h1>
      <LibraryList />
      <CreateLibraryForm />
    </div>
  );
};

export default Home;
