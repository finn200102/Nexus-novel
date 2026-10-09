import React, { useEffect, useRef, useState } from "react";
import { chapterService } from "../../services/chapterService";
import type { RecapData } from "./ReaderPanels";
import { lastReadParagraphs, markRecapShown, shouldShowRecap, readRecapDays, writeRecapDays, daysSince } from "./previouslyOnRule";

interface PreviouslyOnProps {
  novelId: number;
  progress: { chapter_number?: number | null; percent: number; updated_at?: string } | null;
  chapter: { chapter_number: number; title?: string; content: string } | null;
}

/** Dismissible "Previously on…" card shown when a story is reopened after a break. */
export default function PreviouslyOn({ novelId, progress, chapter }: PreviouslyOnProps) {
  const [visible, setVisible] = useState(false);
  const [recap, setRecap] = useState<RecapData | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const lastReadAt = progress?.updated_at ?? null;

  useEffect(() => {
    if (!lastReadAt) return;
    if (!shouldShowRecap({ lastReadAt, novelId, thresholdDays: readRecapDays(), now: new Date() })) return;
    markRecapShown(novelId, lastReadAt);
    returnFocusRef.current = document.activeElement as HTMLElement | null;
    setVisible(true);
    chapterService.getSpoilerSafeRecap(novelId).then(setRecap).catch(() => setRecap(null));
  }, [novelId, lastReadAt]);

  useEffect(() => {
    if (visible) headingRef.current?.focus();
  }, [visible]);

  const dismiss = () => {
    setVisible(false);
    const target = returnFocusRef.current;
    if (target && document.contains(target)) target.focus();
  };

  useEffect(() => {
    if (!visible) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") dismiss();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [visible]);

  if (!visible || !progress || !lastReadAt) return null;

  const days = daysSince(lastReadAt, new Date());
  const chapterNumber = progress.chapter_number ?? 0;
  const sameChapter = chapter !== null && chapter.chapter_number === chapterNumber;
  const chapterLabel = sameChapter && chapter?.title ? `Chapter ${chapterNumber} — ${chapter.title}` : `Chapter ${chapterNumber}`;
  const excerpt = sameChapter && chapter ? lastReadParagraphs(chapter.content, progress.percent) : [];
  const hasRecap = Boolean(recap && recap.chapters.length > 0);

  const hideRecaps = () => {
    writeRecapDays(0);
    dismiss();
  };

  return (
    <section className="previously-on" aria-labelledby="previously-on-title">
      <div className="previously-on__head">
        <h2 id="previously-on-title" tabIndex={-1} ref={headingRef}>Previously on…</h2>
        <button type="button" className="previously-on__close" onClick={dismiss} aria-label="Close recap">×</button>
      </div>
      {hasRecap && recap ? (
        <>
          <p className="previously-on__label">Recap of the chapters you have read (up to chapter {recap.spoiler_boundary_chapter}):</p>
          <ul>{recap.chapters.slice(-3).map((item) => <li key={item.number}>{item.number}. {item.title}</li>)}</ul>
        </>
      ) : (
        <>
          <p className="previously-on__label">
            Last time: {chapterLabel}, {days} {days === 1 ? "day" : "days"} ago.
          </p>
          {excerpt.map((paragraph, index) => <p key={index} className="previously-on__excerpt">{paragraph}</p>)}
        </>
      )}
      <div className="previously-on__foot">
        <button type="button" className="previously-on__link" onClick={hideRecaps}>Hide recaps</button>
      </div>
    </section>
  );
}
