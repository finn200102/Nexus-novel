import React from "react";
import "../../styles/novel-details.css";

interface NovelSchema {
  id?: number;
  title: string;
  author_id?: number;
  url: string;
  library_id?: number;
  cover_image?: string | null;
  created_at?: string;
  updated_at?: string;
}


interface NovelDetailsProps {
  novel: NovelSchema
}

const NovelDetails: React.FC<NovelDetailsProps> = ({
  novel
}) => {
  return (
  <div className="novel-details">     
    <div className="novel-genre">
      <h2>
        Genre
        </h2>
      </div> 
    <div className="novel-tags">
      <h2>
        Tags  
      </h2>
      </div>
    </div>
  );
};

export default NovelDetails;
