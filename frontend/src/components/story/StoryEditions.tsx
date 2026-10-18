import { useEffect, useState, useSyncExternalStore } from "react";
import { Link } from "react-router-dom";
import { Banner, Button } from "../ui";
import { editionReviewService, type ReviewedEditionGroup } from "../../services/editionReviewService";
import { getUserFacingError } from "../../services/apiClient";
import { onAccountStorageChange, storageGeneration } from "../../services/accountStorage";
import "./StoryEditions.css";

function Contents({ metadataId }: { metadataId: number }) {
  const [group, setGroup] = useState<ReviewedEditionGroup | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const generation = storageGeneration();
  useEffect(() => {
    const controller = new AbortController(); let live = true;
    setGroup(null); setError("");
    void editionReviewService.group(metadataId, controller.signal).then(value => {
      if (live && generation === storageGeneration()) setGroup(value);
    }).catch(reason => {
      if (live && generation === storageGeneration()) setError(getUserFacingError(reason, "Reviewed editions could not be loaded."));
    });
    return () => { live = false; controller.abort(); };
  }, [metadataId, generation, attempt]);
  return <section className="story-editions" aria-label="Reviewed editions">
    <h2>Other editions</h2>
    <p>Choose an edition to see its story page. Your library copies and reading positions stay separate. Use “Continue with another source” below to review a progress transfer.</p>
    {error ? <><Banner tone="warning">{error}</Banner><Button variant="secondary" onClick={() => setAttempt(value => value + 1)}>Retry editions</Button></> : !group ? <p role="status">Loading reviewed editions…</p> : !group.reviewed ? <p>No reviewed edition links yet.</p> : <>
      <p>{group.edition_count} available {group.edition_count === 1 ? "edition" : "editions"} in this reviewed group.</p>
      <ul>{group.editions.map(edition => <li key={edition.edition_id}>
        <div><strong>{edition.title}</strong>{edition.author && <span> by {edition.author}</span>}<small>{[edition.site || "Unknown source", edition.language || "Language not recorded", edition.edition_kind.replace(/_/g, " ")].join(" · ")}</small></div>
        {edition.novel_id === metadataId ? <span>Current edition</span> : <Link to={`/story/${edition.novel_id}`}>Open edition<span className="sr-only">: {edition.title} · {edition.site || "Unknown source"} · {edition.language || "Language not recorded"}</span></Link>}
      </li>)}</ul>
    </>}
  </section>;
}
export default function StoryEditions({ metadataId }: { metadataId: number }) {
  const generation = useSyncExternalStore(onAccountStorageChange, storageGeneration);
  return <Contents key={`${generation}:${metadataId}`} metadataId={metadataId} />;
}
