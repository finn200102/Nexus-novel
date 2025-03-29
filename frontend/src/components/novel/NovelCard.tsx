import React from "react";

interface NovelSchema {
  id: number;
  title: string;
  author_id: number;
  url: string;
  library_id: number;
  cover_image: string | null;
  created_at: string;
  updated_at: string;
}

interface NovelCardProps {
  novel: NovelSchema;
  isSelected?: boolean;
  onClick?: () => void;
}

const NovelCard: React.FC<NovelCardProps> = ({
  novel,
  isSelected,
  onClick,
}) => {
  return (
    <div
      className={`novel-card ${isSelected ? "selected" : ""}`}
      onClick={onClick}
    >
      {novel.cover_image && (
        <div className="novel-cover">
          <img
            src={novel.cover_image}
            alt={`Cover for ${novel.title}`}
            className="cover-image"
          />
        </div>
      )}
      <div className="novel-info">
        <h3 className="novel-title">{novel.title}</h3>
        <div className="novel-meta"></div>
      </div>
    </div>
  );
};

export default NovelCard;
