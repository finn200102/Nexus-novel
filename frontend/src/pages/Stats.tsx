import { useEffect, useState, useSyncExternalStore } from "react";
import "../styles/stats.css";
import { usePageTitle } from "../hooks/usePageTitle";
import { EmptyState, PageHeader, SegmentedControl } from "../components/ui";
import { onAccountStorageChange, storageGeneration } from "../services/accountStorage";
import CalendarReview from "../components/stats/CalendarReview";
import DailyBarChart from "../components/stats/DailyBarChart";
import { formatCount, formatDuration } from "../components/stats/statsFormat";
import { readingStatsService, type StatsRange, type StatsSummary } from "../services/readingStatsService";

const RANGE_OPTIONS: { value: StatsRange; label: string }[] = [
  { value: "week", label: "Week" },
  { value: "month", label: "Month" },
  { value: "year", label: "Past 365 days" },
  { value: "all", label: "All time" },
];

const RANGE_NAMES: Record<StatsRange, string> = {
  week: "last 7 days",
  month: "last 30 days",
  year: "last 365 days",
  all: "all time",
};

type LoadState = { status: "loading" } | { status: "error" } | { status: "ready"; data: StatsSummary };

function StatsContents() {
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

  const totals = state.status === "ready" ? state.data.totals : null;
  const hasActivity = !!totals && [totals.seconds, totals.words, totals.chapters_finished, totals.stories_finished, totals.reading_runs_finished, totals.rereads_finished].some(value => (value ?? 0) > 0);
  const completionHistory = state.status === "ready" ? state.data.completion_history : undefined;

  return (
    <div className="stats-page">
      <PageHeader
        title="Reading stats"
        description="Reading time, chapters and completed readings in Nexus."
        actions={
          <SegmentedControl label="Range" options={RANGE_OPTIONS} value={range} onChange={changeRange} />
        }
      />

      {state.status === "loading" && <p role="status">Loading your reading stats…</p>}
      {state.status === "error" && <p role="alert">Couldn’t load your reading stats. Try again later.</p>}

      {state.status === "ready" && !hasActivity && (
        <EmptyState
          title="No reading time yet"
          description="Read a chapter for a few minutes, or mark a reading finished, to see activity in this range."
        />
      )}

      {completionHistory && completionHistory.undated_runs > 0 && <p className="stats-section__note">
        {formatCount(completionHistory.undated_runs)} earlier completed {completionHistory.undated_runs === 1 ? "reading has" : "readings have"} no reliable completion date. {completionHistory.undated_runs_included ? "Undated completions are included in All time totals only." : "Undated completions are excluded from this date range. Choose All time to include them."}
      </p>}

      {state.status === "ready" && hasActivity && (
        <>
          <dl className="stats-tiles">
            <div className="stats-tile"><dt>Time read</dt><dd>{formatDuration(state.data.totals.seconds)}</dd></div>
            <div className="stats-tile"><dt>Words</dt><dd>{formatCount(state.data.totals.words)}</dd></div>
            <div className="stats-tile"><dt>Chapters finished</dt><dd>{formatCount(state.data.totals.chapters_finished)}</dd></div>
            <div className="stats-tile"><dt>Stories finished</dt><dd>{formatCount(state.data.totals.stories_finished)}</dd></div>
            {typeof state.data.totals.reading_runs_finished === "number" && <div className="stats-tile"><dt>Completed readings</dt><dd>{formatCount(state.data.totals.reading_runs_finished)}</dd></div>}
            {typeof state.data.totals.rereads_finished === "number" && <div className="stats-tile"><dt>Rereads finished</dt><dd>{formatCount(state.data.totals.rereads_finished)}</dd></div>}
            <div className="stats-tile">
              <dt>Current streak</dt>
              <dd>{state.data.streak.current} {state.data.streak.current === 1 ? "day" : "days"}</dd>
            </div>
          </dl>
          {typeof state.data.totals.reading_runs_finished === "number" && <p className="stats-section__note">Each story is counted once in this range. Completed readings include first readings and rereads; the reread total counts completed repeat readings.</p>}
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
              <p className="stats-section__note">No timed reading in this range.</p>
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
      <CalendarReview />
    </div>
  );
}


export default function Stats() {
  const generation = useSyncExternalStore(onAccountStorageChange, storageGeneration);
  return <StatsContents key={generation} />;
}
