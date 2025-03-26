import React from "react";
import NovelList from "../components/novel/NovelList";

interface LibraryPageProps {
  library_id: number;
}
const LibraryPage: React.FC<LibraryPageProps> = ({ library_id }) => {
  return (
    <div>
      <NovelList library_id={library_id} />
    </div>
  );
};

export default LibraryPage;
