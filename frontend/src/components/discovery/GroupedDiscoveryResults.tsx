import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Link } from "react-router-dom";
import apiClient, { getUserFacingError } from "../../services/apiClient";
import { onAccountStorageChange, storageGeneration } from "../../services/accountStorage";
import { discoveryFilterParams } from "../../services/discoveryFilters";
import type { DiscoveryFilters } from "../../types/discovery";
import { Banner, Button } from "../ui";
import "./groupedDiscovery.css";
import type { GroupedWork, GroupedWorkPage } from "../../generated/api";
export type { GroupedWork, GroupedWorkPage } from "../../generated/api";
type Props = { site: string; q: string; similarTo: number | null; filters: DiscoveryFilters; refresh: number };
function Contents({ site, q, similarTo, filters, refresh }: Props) {
  const [rows, setRows] = useState<GroupedWork[]>([]), [total, setTotal] = useState(0), [cursor, setCursor] = useState<number | null>(null), [more, setMore] = useState(false), [loading, setLoading] = useState(false), [error, setError] = useState("");
  const generation = storageGeneration(), sequence = useRef(0), mounted = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; sequence.current += 1; }; }, []);
  async function load(append: boolean) {
    const request = ++sequence.current; setLoading(true); setError("");
    try {
      const { data } = await apiClient.get<GroupedWorkPage>("/discovery/works", { params: { ...discoveryFilterParams(filters), ...(site === "all" ? {} : { site }), ...(q ? { q } : {}), ...(similarTo === null ? {} : { similar_to: similarTo }), limit: 20, ...(append && cursor !== null ? { cursor } : {}) }, paramsSerializer: { indexes: null } });
      if (!mounted.current || request !== sequence.current || generation !== storageGeneration()) return;
      setRows(previous => append ? [...previous, ...data.data.filter(item => !previous.some(old => old.group_key === item.group_key))] : data.data); setTotal(data.total); setCursor(data.next_cursor); setMore(data.has_more);
    } catch (err) { if (mounted.current && request === sequence.current && generation === storageGeneration()) setError(getUserFacingError(err, "Grouped catalog results could not be loaded.")); }
    finally { if (mounted.current && request === sequence.current && generation === storageGeneration()) setLoading(false); }
  }
  useEffect(() => { void load(false); /* Query/account changes remount the component; refresh is explicit. */
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refresh]);
  return <section className="grouped-discovery" aria-label="Stories grouped by reviewed work">
    <p>Reviewed editions appear together. Only editions matching your search and content limits are shown. Opening an edition does not import it or move reading progress.</p>
    {error && <Banner tone="danger" action={<Button onClick={() => void load(false)} disabled={loading}>Retry grouped results</Button>}>{error}</Banner>}
    <p role="status">{loading && !rows.length ? "Loading grouped stories…" : `${total.toLocaleString()} matching works`}</p>
    <div className="grouped-discovery-grid">{rows.map(work => <article key={work.group_key}><h2>{work.title}</h2><p>{work.representative.author || "Unknown author"}</p><p>{work.reviewed ? "Reviewed edition group" : "Single catalog edition"} · {work.matching_edition_count} matching {work.matching_edition_count === 1 ? "edition" : "editions"}</p><ul>{work.editions.map(edition => <li key={edition.id}><Link to={`/story/${edition.id}`}>{edition.title}</Link><small>{edition.novel_site} · {edition.author || "Unknown author"}</small></li>)}</ul></article>)}</div>
    {!loading && !error && !rows.length && <p>No catalog stories match this search.</p>}
    {more && cursor !== null && <Button loading={loading} onClick={() => void load(true)}>Load more works</Button>}
  </section>;
}
export default function GroupedDiscoveryResults(props: Props) {
  const generation = useSyncExternalStore(onAccountStorageChange, storageGeneration);
  return <Contents key={`${generation}:${JSON.stringify([props.site, props.q, props.similarTo, props.filters])}`} {...props} />;
}
