import "./CalendarReview.css";
import { useEffect, useState, useSyncExternalStore } from "react";
import { Banner, Button, Select } from "../ui";
import { readingStatsService, type CalendarYearReview } from "../../services/readingStatsService";
import { getUserFacingError } from "../../services/apiClient";
import { onAccountStorageChange, storageGeneration } from "../../services/accountStorage";
import { formatCount, formatDuration } from "./statsFormat";
import ReadingGoal from "./ReadingGoal";
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const dateLabel = (value: string) => new Date(`${value}T12:00:00Z`).toLocaleDateString(undefined, { dateStyle: "long", timeZone: "UTC" });
function Year({ year }: { year: number }) {
  const generation = storageGeneration();
  const [data, setData] = useState<CalendarYearReview | null>(null), [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let active = true;
    void readingStatsService.getCalendarReview(year).then(value => { if (active && generation === storageGeneration()) { setData(value); setError(""); } }).catch(err => { if (active && generation === storageGeneration()) setError(getUserFacingError(err, "Couldn’t load this private year review.")); });
    return () => { active = false; };
  }, [year, generation, refresh]);
  if (!data) return <>{error ? <><Banner tone="warning">{error}</Banner><Button onClick={() => setRefresh(value => value + 1)}>Retry year review</Button></> : <p role="status">Loading your calendar year…</p>}</>;
  const totals = data.summary.totals, undated = data.summary.completion_history?.undated_runs ?? 0;
  const max = Math.max(1, ...data.months.map(month => month.reading_runs_finished));
  return <section aria-label={`Private reading review for ${year}`} className="calendar-review__year">
    <h2>{year} reading review</h2><p>Calendar year: January 1–December 31, {year}.{data.through && ` Totals through ${dateLabel(data.through)}.`} This review is private to your account.</p>
    {!data.tracking_enabled && <p>Reading activity tracking is off. Previously recorded time is kept; completed readings and goals still use your reading journal.</p>}
    {undated > 0 && <p>{formatCount(undated)} earlier completed {undated === 1 ? "reading has" : "readings have"} no reliable completion date. Undated or inferred completions are excluded from this year and its goal; they remain available in All time statistics.</p>}
    <dl className="stats-tiles">
      <div className="stats-tile"><dt>Stories finished in {year}</dt><dd>{formatCount(totals.stories_finished)}</dd></div>
      <div className="stats-tile"><dt>Completed readings in {year}</dt><dd>{formatCount(totals.reading_runs_finished ?? 0)}</dd></div>
      <div className="stats-tile"><dt>Rereads finished in {year}</dt><dd>{formatCount(totals.rereads_finished ?? 0)}</dd></div>
      <div className="stats-tile"><dt>Time read in {year}</dt><dd>{formatDuration(totals.seconds)}</dd></div>
    </dl>
    <ReadingGoal year={year} completed={data.goal.completed_readings} />
    <section aria-label={`Monthly reading activity for ${year}`}><h3>Month by month</h3><p>Completed readings include rereads. Each story is counted once for the year, so monthly story counts can include the same story in different months. Months without activity stay at zero.</p>
      <figure className="stats-chart"><svg className="stats-chart__svg" viewBox="0 0 600 160" role="img" aria-label={`Completed readings by month, ${year}`}>
        {data.months.map((month, index) => { const height = month.reading_runs_finished / max * 152; return <rect key={month.month} x={index * 50 + 8} y={160 - height} width={34} height={height} rx={2} className="stats-chart__bar"><title>{MONTHS[month.month - 1]}: {month.reading_runs_finished} completed readings</title></rect>; })}
      </svg></figure>
      <ol className="calendar-review__months">{data.months.map(month => <li key={month.month}><h4>{MONTHS[month.month - 1]}</h4><p>{formatCount(month.reading_runs_finished)} completed readings · {formatCount(month.rereads_finished)} rereads</p><p>{formatCount(month.stories_finished)} stories · {formatCount(month.chapters_finished)} chapters</p><p>{formatDuration(month.seconds)} reading time · {formatCount(month.words)} words</p></li>)}</ol>
    </section>
  </section>;
}
function Contents() {
  const currentYear = new Date().getUTCFullYear();
  const [year, setYear] = useState(currentYear), [open, setOpen] = useState(false);
  return <details className="calendar-review" onToggle={event => { if (event.target === event.currentTarget) setOpen(event.currentTarget.open); }}>
    <summary>Calendar year review &amp; optional goal</summary>
    {open && <><p>Choose a calendar year for its private review. This is separate from the rolling Past 365 days range above. Goals are optional and unset until you save one.</p>
      <Select label="Review calendar year" value={String(year)} options={Array.from({ length: currentYear - 1899 }, (_, index) => ({ value: String(currentYear - index), label: String(currentYear - index) }))} onChange={event => { const chosen = Number(event.target.value); if (Number.isInteger(chosen) && chosen >= 1900 && chosen <= new Date().getUTCFullYear()) setYear(chosen); }} />
      <Year key={`${storageGeneration()}:${year}`} year={year} />
    </>}
  </details>;
}

export default function CalendarReview() { const generation = useSyncExternalStore(onAccountStorageChange, storageGeneration); return <Contents key={generation} />; }
