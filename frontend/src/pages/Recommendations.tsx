import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import apiClient, { getUserFacingError } from "../services/apiClient";
import { Banner, Button, Cover, EmptyState, PageHeader } from "../components/ui";
import { Compass } from "lucide-react";
import { usePageTitle } from "../hooks/usePageTitle";
import type { DiscoveredNovel } from "../types/discovery";
import "../styles/recommendations.css";
import DiscoveryPreferencesForm from "../components/discovery/DiscoveryPreferencesForm";

type Recommendation = DiscoveredNovel & { reasons: string[]; explanation: string };
export default function Recommendations() {
  usePageTitle("For you");
  const [rows, setRows] = useState<Recommendation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [basis, setBasis] = useState("");
  const [partial, setPartial] = useState(false);
  const load = async () => {
    setLoading(true); setError("");
    try { const result = (await apiClient.get("/recommendations")).data; setRows(result.data ?? []); setBasis(result.basis || "your_library"); setPartial(!!result.source_states?.length); }
    catch (err) { setError(getUserFacingError(err, "Couldn’t load recommendations.")); }
    finally { setLoading(false); }
  };
  useEffect(() => { void load(); }, []);
  const feedback = async (id: number, action: string) => {
    try {
      await apiClient.post("/recommendations/feedback", { metadata_id: id, action });
      if (action !== "opened") setRows((current) => current.filter((row) => row.id !== id));
    } catch (err) { setError(getUserFacingError(err, "Couldn’t save feedback.")); }
  };
  return <div>
    <PageHeader title="For you" description="Suggestions connected to your own reading. Your preferences stay private."
      actions={<Button onClick={() => void apiClient.delete("/recommendations/profile").then(load).catch((err) => setError(getUserFacingError(err, "Couldn’t reset preferences.")))}>Reset recommendation feedback</Button>} />
    {error && <Banner tone="warning">{error}</Banner>}
    <DiscoveryPreferencesForm onSaved={() => void load()} />
    {!loading && <p>{basis === "catalog_feed" ? "Local catalog feed · selected interests can make these more specific." : basis === "your_preferences" ? "Based on your selected interests · reading-history personalization is not required." : "Connected to your library and selected interests."}</p>}
    {partial && <Banner tone="warning">Some catalog requests were unavailable. Available results are shown; try again later.</Banner>}
    {loading ? <p role="status">Finding stories…</p> : !rows.length ? <EmptyState icon={<Compass />} title="Start with a few favorites"
      description="Follow or rate stories you enjoy, then return for suggestions."
      action={<Link to="/discover">Explore Discover</Link>} /> : <ul className="recommendations-grid">
      {rows.map((row) => <li key={row.id}>
        <Cover src={row.img_url} title={row.title} size={112} />
        <h2><Link to={`/story/${row.id}`} onClick={() => void feedback(row.id, "opened")}>{row.title}</Link></h2>
        <p>{row.author} · {row.novel_site}</p>
        {row.reasons.map((reason) => <p key={reason}>{reason}</p>)}
        <Button onClick={() => void feedback(row.id, "not_interested")}>Not interested</Button>
        <Button onClick={() => void feedback(row.id, "already_read")}>Already read</Button>
        <Link to={`/discover?similar_to=${row.id}`}>More like this</Link>
      </li>)}
    </ul>}
  </div>;
}
