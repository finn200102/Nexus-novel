import React, { useState, useEffect } from "react";
import { libraryService } from "../../services/libraryService";
import { useNavigate } from "react-router-dom";
import "../../styles/library-list.css";

interface LibrarySchema {
  id: number;
  name: string;
  user_id: number;
}

const LibraryList: React.FC = () => {
  const [libraries, setLibraries] = useState<LibrarySchema[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    const fetchLibraries = async () => {
      try {
        setLoading(true);
        const data = await libraryService.getLibraries();

        // Ensure we have an array of libraries
        if (Array.isArray(data)) {
          setLibraries(data);
        } else {
          console.error("Expected array but got:", data);
          setError("Unexpected data format");
        }
      } catch (err) {
        console.error("Failed to fetch libraries:", err);
        setError("Failed to load libraries");
      } finally {
        setLoading(false);
      }
    };

    fetchLibraries();
  }, []);

  const handleLibraryClick = (libraryId: number) => {
    navigate(`/library/${libraryId}`);
  };

  return (
    <div className="library-container">
      <h2 className="library-title">My Libraries</h2>

      {loading && <p className="loading-message">Loading...</p>}

      {error && <p className="error-message">{error}</p>}

      {!loading && libraries.length === 0 && (
        <p className="empty-state-message">No libraries found</p>
      )}

      {libraries.length > 0 && (
        <ul className="library-items">
          {libraries.map((library) => (
            <li
              key={library.id}
              onClick={() => handleLibraryClick(library.id)}
              className="library-item"
            >
              {library.name}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

export default LibraryList;
