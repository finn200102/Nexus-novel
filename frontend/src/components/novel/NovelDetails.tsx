import React from "react";
import { Novel } from "../../types/novel";
import "../../styles/novel-details.css";

interface NovelDetailsProps {
  novel: Novel;
}

const formatNumber = (num: number | null | undefined): string => {
  if (num === null || num === undefined) return "N/A";
  if (num >= 1000000) return (num / 1000000).toFixed(1) + "M";
  if (num >= 1000) return (num / 1000).toFixed(1) + "K";
  return num.toString();
};

const formatDate = (dateStr: string | null | undefined): string => {
  if (!dateStr) return "N/A";
  try {
    const date = new Date(dateStr);
    return date.toLocaleDateString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return dateStr;
  }
};

const getSiteDisplayName = (site: string | null | undefined): string => {
  if (!site) return "Unknown";
  const sites: Record<string, string> = {
    royalroad: "Royal Road",
    fanfiction: "FanFiction.Net",
    spacebattles: "SpaceBattles",
    archive: "Archive of Our Own",
    webnovel: "WebNovel",
    sufficientvelocity: "Sufficient Velocity",
    questionablequesting: "Questionable Questing",
    scribblehub: "ScribbleHub",
  };
  return sites[site.toLowerCase()] || site;
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

const NovelDetails: React.FC<NovelDetailsProps> = ({ novel }) => {
  const stats = [
    { label: "Word Count", value: formatNumber(novel.word_count), icon: "📖" },
    { label: "Chapters", value: novel.chapter_count ?? "—", icon: "📑" },
    { label: "Views", value: formatNumber(novel.views), icon: "👁" },
    { label: "Favorites", value: formatNumber(novel.favorites), icon: "❤️" },
    { label: "Reviews", value: formatNumber(novel.reviews), icon: "💬" },
    { label: "Follows", value: formatNumber(novel.follows), icon: "🔖" },
  ];

  const infoRows = [
    { label: "Author", value: novel.author || "Unknown Author" },
    { label: "Status", value: getDisplayStatus(novel) },
    { label: "Published", value: formatDate(novel.publish_date) },
    { label: "Updated", value: formatDate(novel.updated_date) },
  ];

  const rating = novel.rating ?? 0;
  const fullStars = Math.floor(rating);
  const hasHalfStar = rating % 1 >= 0.5;
  const emptyStars = 5 - fullStars - (hasHalfStar ? 1 : 0);
  const displayStatus = getDisplayStatus(novel);

  return (
    <div className="novel-details-container">
      <div className="novel-info-grid">
        <div className="novel-main-info">
          <div className="novel-meta-row">
            <span className="novel-site-badge">
              {getSiteDisplayName(novel.novel_site)}
            </span>
            {displayStatus && displayStatus !== "Unknown" && (
              <span className={`novel-status-badge status-${displayStatus.toLowerCase().replace(/\s+/g, '-')}`}>
                {displayStatus}
              </span>
            )}
          </div>

          <div className="novel-info-rows">
            {infoRows.map((row) => (
              <div key={row.label} className="novel-info-row">
                <span className="label">{row.label}</span>
                <span className="value">{row.value}</span>
              </div>
            ))}
          </div>

          <div className="novel-rating">
            <span className="label">Rating</span>
            <div className="stars">
              {[...Array(fullStars)].map((_, i) => (
                <span key={`full-${i}`} className="star full">★</span>
              ))}
              {hasHalfStar && <span className="star half">★</span>}
              {[...Array(emptyStars)].map((_, i) => (
                <span key={`empty-${i}`} className="star empty">☆</span>
              ))}
              <span className="rating-value">({rating.toFixed(1)})</span>
            </div>
          </div>

          {novel.source_url && (
            <div className="novel-source">
              <a href={novel.source_url} target="_blank" rel="noopener noreferrer" className="source-link">
                View on {getSiteDisplayName(novel.novel_site)} →
              </a>
            </div>
          )}
        </div>

        <div className="novel-stats-grid">
          {stats.map((stat) => (
            <div key={stat.label} className="stat-item">
              <span className="stat-icon">{stat.icon}</span>
              <span className="stat-value">{stat.value}</span>
              <span className="stat-label">{stat.label}</span>
            </div>
          ))}
        </div>
      </div>

      {novel.description && (
        <div className="novel-description-section">
          <h3>Synopsis</h3>
          <p className="novel-description">{novel.description}</p>
        </div>
      )}

      <div className="novel-metadata-info">
        {novel.metadata_id && (
          <span className="metadata-id">Metadata ID: {novel.metadata_id}</span>
        )}
        {novel.story_id && (
          <span className="story-id">Story ID: {novel.story_id}</span>
        )}
        {novel.parsed_at && (
          <span className="parsed-at">Last synced: {formatDate(novel.parsed_at)}</span>
        )}
      </div>
    </div>
  );
};

export default NovelDetails;
