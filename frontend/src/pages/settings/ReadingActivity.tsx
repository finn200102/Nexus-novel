import { useEffect, useSyncExternalStore } from "react";
import { Link } from "react-router-dom";
import { PageHeader, Button, Switch } from "../../components/ui";
import { usePageTitle } from "../../hooks/usePageTitle";
import { readingActivityService } from "../../services/readingActivityService";
import { SETTINGS_BACK } from "./settingsNav";

export default function ReadingActivity() {
  usePageTitle("Reading activity", { back: SETTINGS_BACK });
  const state = useSyncExternalStore(readingActivityService.subscribe, readingActivityService.snapshot);
  useEffect(() => { void readingActivityService.load(); }, [state.generation]);
  return <>
    <PageHeader title="Reading activity" description="Choose whether Nexus measures your reading activity." />
    <section className="settings-group" aria-labelledby="reading-measurement">
      <h2 id="reading-measurement">Reading statistics</h2>
      <p>Record reading time, estimated words and daily chapter counts for your private statistics. This account setting follows you across devices.</p>
      <p>Turning measurement off keeps your saved place, reading history, completion records and existing statistics. Ordinary reading and listening continue to work.</p>
      {!state.loaded && !state.error && <p role="status">Checking your setting…</p>}
      <Switch label="Measure reading activity" checked={state.preferences?.values.tracking_enabled ?? false} disabled={!state.loaded || state.busy || !!state.pending} onChange={enabled => void readingActivityService.change(enabled)} />
      {state.pending && <p role="status">A setting change still needs confirmation. This device has paused measurement.</p>}
      {state.loaded && !state.pending && <p role="status">{state.preferences?.values.tracking_enabled ? "Reading measurement is on." : "Reading measurement is off."}</p>}
      {state.error && <p role="alert">{state.error}</p>}
      {state.pending && <div className="settings-actions">
        <Button disabled={state.busy} onClick={() => void readingActivityService.retry()}>Retry same change</Button>
        <Button disabled={state.busy} onClick={() => void readingActivityService.useServerSetting()}>Use current server setting</Button>
        <p>Using the server setting resumes measurement if it is on there.</p>
      </div>}
      {!state.loaded && !state.pending && !!state.error && <Button onClick={() => void readingActivityService.load()}>Check setting again</Button>}
    </section>
    <section className="settings-group" aria-labelledby="optional-reading-goals">
      <h2 id="optional-reading-goals">Optional goals and year review</h2>
      <p>Set a personal reading goal only if it helps you. Goals stay on your statistics page and never interrupt a chapter. A year review uses your existing private activity and dated completions.</p>
      <Link to="/stats">Open reading statistics</Link>
    </section>
  </>;
}
