import React, { useState } from "react";
import DiscoveryList from "../components/discovery/DiscoveryList";

interface DiscoveryProps {
  libraryId: number;
}

const availableSources = ["royalroad"];

const Discovery: React.FC<DiscoveryProps> = ({ libraryId }) => {
  const [selectedSource, setSelectedSource] = useState<string>(
    availableSources[0]
  );

  const handleChange = (event: React.ChangeEvent<HTMLSelectElement>) => {
    setSelectedSource(event.target.value);
  };

  return (
    <div className="discovery-page">
      <h1>Search Trending Novels</h1>

      <div className="source-selector">
        <label htmlFor="source-select">Select Source:</label>
        <select
          id="source-select"
          value={selectedSource}
          onChange={handleChange}
        >
          {availableSources.map((source) => (
            <option key={source} value={source}>
              {source}
            </option>
          ))}
        </select>
      </div>

      <DiscoveryList source={selectedSource} library_id={libraryId} />
    </div>
  );
};

export default Discovery;
