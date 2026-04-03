import React from "react";
import defaultCoverImage from "../../assets/cover.png";
import { Novel } from "../../types/novel";
import "../../styles/novel-card.css";

interface NovelCardProps {
  novel: Novel;
  isSelected?: boolean;
  onClick?: () => void;
}

const formatWordCount = (wordCount: number | null | undefined): string => {
  if (wordCount === null || wordCount === undefined) return "—";
  if (wordCount >= 1000000) return `${(wordCount / 1000000).toFixed(1)}M`;
  if (wordCount >= 1000) return `${(wordCount / 1000).toFixed(0)}K`;
  return `${wordCount}`;
};

const getDisplayStatus = (novel: Novel): string => {
  if (novel.status === "Complete") return "Complete";
  
  if (novel.updated_date) {
    const updated = new Date(novel.updated_date);
    const oneYearAgo = new Date();
    oneYearAgo.setFullYear(oneYearAgo.getFullYear() - 1);
    
    if (updated > oneYearAgo) {
      return "Ongoing";
    }
  }
  
  return novel.status || "Unknown";
};

const NovelCard: React.FC<NovelCardProps> = ({
  novel,
  isSelected,
  onClick,
}) => {
  const coverImageSrc = novel.img_url || novel.cover_image || defaultCoverImage;
  const displayStatus = getDisplayStatus(novel);
  const updatedDate = novel.updated_date
    ? new Date(novel.updated_date).toLocaleDateString()
    : null;

  const statItems = [
    {
      label: "Words",
      value: formatWordCount(novel.word_count),
    },
    {
      label: "Chapters",
      value: novel.chapter_count !== null && novel.chapter_count !== undefined ? novel.chapter_count : "—",
    },
    {
      label: "Rating",
      value:
        novel.rating !== null && novel.rating !== undefined
          ? novel.rating.toFixed(1)
          : "—",
    },
    {
      label: "Views",
      value: formatWordCount(novel.views),
    },
    {
      label: "Favorites",
      value: formatWordCount(novel.favorites),
    },
  ];

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
          referrerPolicy="no-referrer"
          onError={(e) => {
            (e.target as HTMLImageElement).src = defaultCoverImage;
          }}
        />
      </div>
      <div className="novel-card__content">
        <div className="novel-card__badge-row">
          {novel.novel_site && (
            <span className="novel-card__badge">
              {novel.novel_site.toUpperCase()}
            </span>
          )}
          {novel.scrape_status && novel.scrape_status !== "completed" && (
            <span className={`novel-card__scrape novel-card__scrape--${novel.scrape_status}`}>
              {novel.scrape_status === "pending" ? "Pending" : "Needs Attention"}
            </span>
          )}
        </div>
        <h3 className="novel-card__title">{novel.title}</h3>
        <div className="novel-card__meta">
          <span className="novel-card__author">{novel.author || "Unknown Author"}</span>
          <div className="novel-card__stats">
            {statItems.map((stat) => (
              <span key={stat.label} className="novel-card__stat">
                <span className="novel-card__stat-label">{stat.label}</span>
                <span className="novel-card__stat-value">{stat.value}</span>
              </span>
            ))}
          </div>
          {displayStatus && displayStatus !== "Unknown" && (
            <span className={`novel-card__status status-${displayStatus.toLowerCase().replace(/\s+/g, '-')}`}>
              {displayStatus}
            </span>
          )}
          {updatedDate && (
            <span className="novel-card__updated">Updated {updatedDate}</span>
          )}
        </div>
      </div>
    </div>
  );
};

export default NovelCard;
