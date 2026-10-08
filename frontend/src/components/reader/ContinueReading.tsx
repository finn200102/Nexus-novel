import React, { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import apiClient from "../../services/apiClient";
import { displayTitle } from "../../utils/displayTitle";
import { Badge, Button, Cover, Progress } from "../ui";
import type { Novel } from "../../types/novel";
import type { InboxNovel } from "../../types/activity";
import "../../styles/home.css";

export interface RecentProgress {
  novel_id: number;
  novel_title: string;
  library_id: number;
  chapter_number: number | null;
  position: number;
  percent: number;
  updated_at: string;
}

interface ContinueReadingProps {
  limit?: number;
  /** Library stories, used for covers, authors and chapter totals. */
  novels?: Novel[];
  /** Unread update rows, used for the "N new" badge. */
  updates?: InboxNovel[];
}

/**
 * Home resume row: the most recently read story as a large card (one primary Continue),
 * the rest as compact cards. Renders nothing when there is no reading history.
 */
const ContinueReading: React.FC<ContinueReadingProps> = ({ limit = 8, novels = [], updates = [] }) => {
  const navigate = useNavigate();
  const [items, setItems] = useState<RecentProgress[]>([]);

  useEffect(() => {
    let cancelled = false;
    apiClient.get<RecentProgress[]>("/chapter/progress/recent", { params: { limit } })
      .then((response) => {
        if (!cancelled && Array.isArray(response.data)) {
          setItems(response.data.filter((item) => item.chapter_number !== null));
        }
      })
      .catch(() => { if (!cancelled) setItems([]); });
    return () => { cancelled = true; };
  }, [limit]);

  const novelById = useMemo(() => new Map(novels.map((novel) => [novel.id, novel])), [novels]);
  const newByNovel = useMemo(() => new Map(updates.map((row) => [row.novel_id, row.new_chapter_count])), [updates]);

  if (items.length === 0) return null;

  const [hero, ...rest] = items;
  const open = (item: RecentProgress) =>
    navigate(`/library/${item.library_id}/novels/${item.novel_id}/${item.chapter_number}`);

  const details = (item: RecentProgress) => {
    const novel = novelById.get(item.novel_id);
    const total = novel?.chapter_count ?? null;
    const chapter = total ? `Chapter ${item.chapter_number} of ${total}` : `Chapter ${item.chapter_number}`;
    return { novel, chapter, percent: Math.round(item.percent) };
  };

  const heroDetails = details(hero);
  const heroTitle = displayTitle({ title: hero.novel_title });
  const heroNew = newByNovel.get(hero.novel_id) ?? 0;

  return (
    <section className="resume" aria-labelledby="resume-heading">
      <h2 id="resume-heading" className="resume__heading">Continue reading</h2>

      <article className="resume-hero">
        <Cover src={heroDetails.novel?.img_url || heroDetails.novel?.cover_image} title={heroTitle} author={heroDetails.novel?.author} size={112} />
        <div className="resume-hero__body">
          {heroNew > 0 && <Badge tone="accent">{heroNew} new</Badge>}
          <h3 className="resume-hero__title">{heroTitle}</h3>
          {heroDetails.novel?.author && <p className="resume-hero__author">by {heroDetails.novel.author}</p>}
          <p className="resume-hero__progress">{heroDetails.chapter} · {heroDetails.percent}%</p>
          <Progress label={`Reading progress for ${heroTitle}`} value={heroDetails.percent} valueText={`${heroDetails.percent}%`} />
          <Button variant="primary" onClick={() => open(hero)} aria-label={`Continue reading ${heroTitle}, ${heroDetails.chapter}`}>
            Continue
          </Button>
        </div>
      </article>

      {rest.length > 0 && (
        <ul className="resume-row" aria-label="Other stories you are reading">
          {rest.map((item) => {
            const { novel, chapter, percent } = details(item);
            const title = displayTitle({ title: item.novel_title });
            const fresh = newByNovel.get(item.novel_id) ?? 0;
            return (
              <li key={`${item.novel_id}-${item.chapter_number}`} className="resume-row__item">
                <button type="button" className="resume-card" onClick={() => open(item)} aria-label={`${title}, ${chapter}, ${percent}%`}>
                  <Cover src={novel?.img_url || novel?.cover_image} title={title} size={72} />
                  <span className="resume-card__body">
                    {fresh > 0 && <Badge tone="accent">{fresh} new</Badge>}
                    <strong>{title}</strong>
                    <span className="resume-card__meta">{chapter} · {percent}%</span>
                    <Progress label={`Reading progress for ${title}`} value={percent} valueText={`${percent}%`} />
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
};

export default ContinueReading;
