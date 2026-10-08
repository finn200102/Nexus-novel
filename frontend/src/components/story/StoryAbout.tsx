import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ChevronDown } from "lucide-react";
import { ReasonList } from "../organization/ReasonList";
import type { InsightSignal, SimilarNovel, StoryGuide } from "../../services/insightService";
import { Button, Card, Menu, Progress } from "../ui";
import { discoverTagLink, type StoryView } from "./storyModel";

type TermKind = "tag" | "genre" | "fandom";

interface StoryAboutProps {
  view: StoryView;
  inLibrary: boolean;
  signals: InsightSignal[];
  analysisState: string;
  enriching: boolean;
  onEnrich: () => void;
  similar: SimilarNovel[];
  guide: StoryGuide | null;
  guideCutoff: number;
  buildingGuide: boolean;
  onBuildGuide: () => void;
  onHide: (kind: TermKind | "author", value: string) => void;
  progress: { read: number; total: number } | null;
  onSaveNext: () => void;
  savingOffline: boolean;
  offlineCount: number;
}

const LONG_SYNOPSIS = 600;
const KIND_LABEL: Record<TermKind, string> = { tag: "tag", genre: "genre", fandom: "fandom" };

/** A tag chip that opens a menu: find stories with it, or hide them (no per-tag Hide pills). */
const TermChip: React.FC<{ kind: TermKind; value: string; onHide: StoryAboutProps["onHide"] }> = ({ kind, value, onHide }) => {
  const navigate = useNavigate();
  return (
    <Menu
      trigger={(props) => (
        <button {...props} type="button" className="story-term" aria-label={`${value}, ${KIND_LABEL[kind]} options`}>
          {value}
          <ChevronDown size={14} aria-hidden="true" />
        </button>
      )}
      items={[
        { label: `Find stories with this ${KIND_LABEL[kind]}`, onSelect: () => navigate(discoverTagLink(kind, value)) },
        { label: `Hide stories with this ${KIND_LABEL[kind]}`, onSelect: () => onHide(kind, value) },
      ]}
    />
  );
};

const TermGroup: React.FC<{ title: string; kind: TermKind; values: string[]; onHide: StoryAboutProps["onHide"] }> = ({ title, kind, values, onHide }) => {
  if (values.length === 0) return null;
  return (
    <section className="story-section" aria-labelledby={`story-terms-${kind}`}>
      <h2 id={`story-terms-${kind}`} className="story-section__title">{title}</h2>
      <ul className="story-chips" role="list">
        {values.map((value) => (
          <li key={value}><TermChip kind={kind} value={value} onHide={onHide} /></li>
        ))}
      </ul>
    </section>
  );
};

/** About tab: synopsis, tags, writing style, story guide; progress and similar stories alongside. */
const StoryAbout: React.FC<StoryAboutProps> = (props) => {
  const { view, inLibrary, signals, analysisState, enriching, onEnrich, similar, guide, guideCutoff, buildingGuide, onBuildGuide, onHide, progress } = props;
  const [expanded, setExpanded] = useState(false);
  const long = (view.description?.length ?? 0) > LONG_SYNOPSIS;
  const running = analysisState === "queued" || analysisState === "running";
  const guideLink = view.metadataId ? `/story/${view.metadataId}/guide?through_chapter=${guideCutoff}` : null;

  return (
    <div className="story-body">
      <div className="story-main">
        <section className="story-section" aria-labelledby="story-synopsis">
          <h2 id="story-synopsis" className="visually-hidden">Synopsis</h2>
          {view.description ? (
            <>
              <p id="story-synopsis-text" className={`story-synopsis${long && !expanded ? " story-synopsis--clamped" : ""}`}>{view.description}</p>
              {long && (
                <Button variant="ghost" size="sm" className="story-synopsis__toggle" aria-expanded={expanded} aria-controls="story-synopsis-text" onClick={() => setExpanded((value) => !value)}>
                  {expanded ? "Show less" : "Show more"}
                </Button>
              )}
            </>
          ) : (
            <p className="story-hint">No synopsis from the source.</p>
          )}
        </section>

        <TermGroup title="Tags" kind="tag" values={view.tags} onHide={onHide} />
        <TermGroup title="Genres" kind="genre" values={view.genres} onHide={onHide} />
        <TermGroup title="Fandoms" kind="fandom" values={view.fandoms} onHide={onHide} />
        {view.tags.length + view.genres.length + view.fandoms.length > 0 && (
          <p className="story-hint">Select a tag to find similar stories or hide it.</p>
        )}

        {view.metadataId && (
          <details className="story-disclosure">
            <summary>Writing style (estimated)</summary>
            <div className="story-disclosure__body">
              <p className="story-hint">Estimated from the text on this server. Source tags are not changed.</p>
              {signals.length > 0 ? (
                <ul className="story-chips" role="list">
                  {signals.map((signal) => (
                    <li key={`${signal.family}:${signal.value}`} className="story-signal">
                      {signal.family.replace(/_/g, " ")}: <strong>{signal.value}</strong>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="story-row">
                  <span className="story-hint">{running ? "Estimating in the background…" : "Not estimated yet."}</span>
                  <Button size="sm" variant="secondary" loading={enriching} disabled={running} onClick={onEnrich}>
                    {running ? "Estimate queued" : "Estimate writing style"}
                  </Button>
                </div>
              )}
            </div>
          </details>
        )}

        {guide && !guide.unavailable && guideLink && (
          <Card className="story-card">
            <h2 className="story-section__title">Story guide</h2>
            {guide.chapters_analyzed ? (
              <>
                <p className="story-hint">Characters, places and recaps through chapter {guide.through_chapter}. Later chapters are left out, so nothing is spoiled.</p>
                {guide.characters?.length > 0 && (
                  <p className="story-guide-names">{guide.characters.slice(0, 6).map((character) => character.name).join(" · ")}</p>
                )}
                <Link className="story-link" to={guideLink}>Open story guide</Link>
              </>
            ) : (
              <>
                <p className="story-hint">Build a spoiler-free guide to characters, places and events from your downloaded chapters.</p>
                <div className="story-row">
                  {inLibrary && (
                    <Button size="sm" variant="secondary" loading={buildingGuide} onClick={onBuildGuide}>Build story guide</Button>
                  )}
                  <Link className="story-link" to={guideLink}>Open story guide</Link>
                </div>
              </>
            )}
          </Card>
        )}
      </div>

      <aside className="story-aside" aria-label="Progress and similar stories">
        {inLibrary && progress && (
          <Card className="story-card">
            <h2 className="story-section__title">Your progress</h2>
            <Progress label="Chapters read" value={progress.read} max={Math.max(progress.total, 1)} valueText={`${progress.read} of ${progress.total} read`} />
            <p className="story-hint">{progress.read} of {progress.total} read · {props.offlineCount} saved offline</p>
            <Button size="sm" variant="secondary" disabled={props.savingOffline} onClick={props.onSaveNext}>Save next 10 offline</Button>
          </Card>
        )}
        {similar.length > 0 && (
          <Card className="story-card">
            <h2 className="story-section__title">Similar stories</h2>
            <ul className="story-similar" role="list">
              {similar.slice(0, 6).map((match) => (
                <li key={match.novel_id} className="story-similar__item">
                  <Link to={`/story/${match.novel_id}`} className="story-similar__title">{match.title}</Link>
                  <span className="story-hint">{[match.author, match.explanation].filter(Boolean).join(" · ")}</span>
                  <ReasonList reasons={match.reasons} />
                </li>
              ))}
            </ul>
            {view.metadataId && <Link className="story-link" to={`/discover/all?similar_to=${view.metadataId}`}>Browse all similar stories</Link>}
          </Card>
        )}
      </aside>
    </div>
  );
};

export default StoryAbout;
