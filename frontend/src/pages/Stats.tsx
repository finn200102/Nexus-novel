import { useEffect, useState } from "react";
import "../styles/stats.css";
import { usePageTitle } from "../hooks/usePageTitle";
import { EmptyState, PageHeader, SegmentedControl } from "../components/ui";
import DailyBarChart from "../components/stats/DailyBarChart";
import { formatCount, formatDuration } from "../components/stats/statsFormat";
import { readingStatsService, type StatsRange, type StatsSummary } from "../services/readingStatsService";

const RANGE_OPTIONS: { value: StatsRange; label: string }[] = [
  { value: "week", label: "Week" },
  { value: "month", label: "Month" },
  { value: "year", label: "Year" },
  { value: "all", label: "All time" },
];

const RANGE_NAMES: Record<StatsRange, string> = {
  week: "last 7 days",
  month: "last 30 days",
  year: "last 365 days",
  all: "all time",
};

type LoadState = { status: "loading" } | { status: "error" } | { status: "ready"; data: StatsSummary };

export default function Stats() {
  usePageTitle("Reading stats");
  const [range, setRange] = useState<StatsRange>("week");
  const [state, setState] = useState<LoadState>({ status: "loading" });

  useEffect(() => {
    let active = true;
    readingStatsService
      .getSummary(range)
      .then((data) => active && setState({ status: "ready", data }))
      .catch(() => active && setState({ status: "error" }));
    return () => {
      active = false;
    };
  }, [range]);

  const changeRange = (next: StatsRange) => {
    setState({ status: "loading" });
    setRange(next);
  };

  return (
    <div className="stats-page">
      <PageHeader
        title="Reading stats"
        description="Time, words and chapters you have read in Nexus."
        actions={
          <SegmentedControl label="Range" options={RANGE_OPTIONS} value={range} onChange={changeRange} />
        }
      />

      {state.status === "loading" && <p role="status">Loading your reading stats…</p>}
      {state.status === "error" && <p role="alert">Couldn’t load your reading stats. Try again later.</p>}

      {state.status === "ready" && state.data.totals.seconds === 0 && (
        <EmptyState
          title="No reading time yet"
          description="Read a chapter for a few minutes and your stats will appear here."
        />
      )}

      {state.status === "ready" && state.data.totals.seconds > 0 && (
        <>
          <dl className="stats-tiles">
            <div className="stats-tile"><dt>Time read</dt><dd>{formatDuration(state.data.totals.seconds)}</dd></div>
            <div className="stats-tile"><dt>Words</dt><dd>{formatCount(state.data.totals.words)}</dd></div>
            <div className="stats-tile"><dt>Chapters finished</dt><dd>{formatCount(state.data.totals.chapters_finished)}</dd></div>
            <div className="stats-tile"><dt>Stories finished</dt><dd>{formatCount(state.data.totals.stories_finished)}</dd></div>
            <div className="stats-tile">
              <dt>Current streak</dt>
              <dd>{state.data.streak.current} {state.data.streak.current === 1 ? "day" : "days"}</dd>
            </div>
          </dl>
          <p className="stats-section__note">
            Longest streak: {state.data.streak.longest} {state.data.streak.longest === 1 ? "day" : "days"}. A day counts
            with at least 5 minutes of reading.
          </p>

          <section className="stats-section" aria-labelledby="stats-daily">
            <h2 id="stats-daily">Reading time per day, {RANGE_NAMES[range]}</h2>
            <DailyBarChart
              data={state.data.daily}
              label={`Reading time per day, ${RANGE_NAMES[range]}`}
            />
          </section>

          <section className="stats-section" aria-labelledby="stats-top">
            <h2 id="stats-top">Top stories</h2>
            {state.data.top_stories.length ? (
              <ol className="stats-list">
                {state.data.top_stories.map((story) => (
                  <li key={story.novel_id}>
                    <span>{story.title}</span>
                    <span className="stats-list__value">{formatDuration(story.seconds)}</span>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="stats-section__note">No stories in this range.</p>
            )}
          </section>

          <section className="stats-section" aria-labelledby="stats-site">
            <h2 id="stats-site">By site</h2>
            <ul className="stats-list">
              {state.data.by_site.map((row) => (
                <li key={row.site}>
                  <span>{row.site}</span>
                  <span className="stats-list__value">{formatDuration(row.seconds)}</span>
                </li>
              ))}
            </ul>
          </section>

          {state.data.by_tag.length > 0 && (
            <section className="stats-section" aria-labelledby="stats-tag">
              <h2 id="stats-tag">By tag</h2>
              <ul className="stats-list">
                {state.data.by_tag.map((row) => (
                  <li key={row.tag}>
                    <span>{row.tag}</span>
                    <span className="stats-list__value">{formatDuration(row.seconds)}</span>
                  </li>
                ))}
              </ul>
              <p className="stats-section__note">A story with several tags counts toward each of them.</p>
            </section>
          )}
        </>
      )}
    </div>
  );
}
