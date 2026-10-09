import type { DailyStat } from "../../services/readingStatsService";
import { formatCount, formatDayLabel, formatDuration } from "./statsFormat";

interface DailyBarChartProps {
  data: DailyStat[];
  /** Accessible name, e.g. "Reading time per day, last 7 days". */
  label: string;
}

const WIDTH = 600;
const HEIGHT = 160;

/** Inline SVG bars with a screen-reader table carrying the same numbers. */
export default function DailyBarChart({ data, label }: DailyBarChartProps) {
  const max = Math.max(1, ...data.map((day) => day.seconds));
  const slot = data.length ? WIDTH / data.length : WIDTH;
  const barWidth = Math.max(1, slot * 0.7);

  return (
    <figure className="stats-chart">
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label={label} preserveAspectRatio="none" className="stats-chart__svg">
        {data.map((day, index) => {
          const height = (day.seconds / max) * (HEIGHT - 8);
          return (
            <rect
              key={day.date}
              x={index * slot + (slot - barWidth) / 2}
              y={HEIGHT - height}
              width={barWidth}
              height={Math.max(height, day.seconds > 0 ? 2 : 0)}
              rx={2}
              className="stats-chart__bar"
            >
              <title>{`${formatDayLabel(day.date)}: ${formatDuration(day.seconds)}`}</title>
            </rect>
          );
        })}
      </svg>
      <table className="sr-only">
        <caption>{label}</caption>
        <thead>
          <tr>
            <th scope="col">Day</th>
            <th scope="col">Reading time</th>
            <th scope="col">Words</th>
            <th scope="col">Chapters finished</th>
          </tr>
        </thead>
        <tbody>
          {data.map((day) => (
            <tr key={day.date}>
              <th scope="row">{formatDayLabel(day.date)}</th>
              <td>{formatDuration(day.seconds)}</td>
              <td>{formatCount(day.words)}</td>
              <td>{day.chapters_finished}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
