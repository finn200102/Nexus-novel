import React from "react";
import defaultCoverImage from "../../assets/cover.png";
import "../../styles/novel-card.css";

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
  const coverImageSrc = novel.cover_image || defaultCoverImage;

  return (
    <div
      className={`novel-card ${isSelected ? "novel-card--selected" : ""}`}
      onClick={onClick}
    >
      <div className="novel-card__cover">
        <img
          src={coverImageSrc}
          alt={`Cover for ${novel.title}`}
          className="novel-card__image"
          onError={(e) => {
            (e.target as HTMLImageElement).src = defaultCoverImage;
          }}
        />
      </div>
      <div className="novel-card__content">
        <h3 className="novel-card__title">{novel.title}</h3>
        <div className="novel-card__meta"></div>
      </div>
    </div>
  );
};

export default NovelCard;
