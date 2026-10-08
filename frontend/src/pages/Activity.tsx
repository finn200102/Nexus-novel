import React, { useEffect, useState } from "react";
import { CalendarDays, CheckCircle2, Download, RefreshCw } from "lucide-react";
import { useLibraryContext } from "../context/useLibraryContext";
import { activityService } from "../services/activityService";
import type { ActivityDay, ActivityEvent } from "../types/activity";
import "../styles/activity.css";

const Activity: React.FC = () => {
  const { activeLibrary } = useLibraryContext();
  const activeLibraryId = activeLibrary?.id;
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [days, setDays] = useState<ActivityDay[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (activeLibraryId === undefined) { setEvents([]); setDays([]); setLoading(false); return; }
    setLoading(true);
    Promise.all([activityService.getFeed(activeLibraryId), activityService.getCalendar(activeLibraryId)])
      .then(([feed, calendar]) => { setEvents(feed); setDays(calendar); })
      .catch((error) => console.error("Failed to load activity", error))
      .finally(() => setLoading(false));
  }, [activeLibraryId]);

  return <div className="activity-page">
    <header className="activity-page__header"><div><p className="library-workspace__eyebrow">Activity</p><h1>Updates & activity</h1><p>Follow changes, source failures, and download progress in one place.</p></div><RefreshCw size={20} aria-hidden="true" /></header>
    {loading && <p className="activity-page__empty">Loading activity…</p>}
    {!loading && !activeLibrary && <p className="activity-page__empty">Create or select a library to see activity.</p>}
    {!loading && activeLibrary && <>
      <section className="activity-calendar" aria-label="Activity calendar">
        <div className="activity-section__title"><CalendarDays size={18} /><h2>Recent days</h2></div>
        {days.length === 0 && <p className="activity-page__empty">No activity recorded yet.</p>}
        <div className="activity-calendar__grid">{days.map((day) => <article key={day.date} className="activity-day"><strong>{new Date(`${day.date}T00:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" })}</strong><span>{day.chapter_count} chapters</span><small>{day.event_count} events · {day.downloads_completed} downloads</small></article>)}</div>
      </section>
      <section className="activity-feed"><div className="activity-section__title"><CheckCircle2 size={18} /><h2>Feed</h2></div>
        {events.length === 0 && <p className="activity-page__empty">No recent events.</p>}
        {events.map((event) => <article key={event.id} className="activity-event"><span className="activity-event__icon"><Download size={16} /></span><div><strong>{event.novel_title}</strong><p>{event.message}</p><small>{new Date(event.created_at).toLocaleString()} · {event.event_type.replace(/_/g, " ")}</small></div>{event.read_at ? <span className="activity-event__read">Read</span> : <span className="activity-event__new">New</span>}</article>)}
      </section>
    </>}
  </div>;
};

export default Activity;
