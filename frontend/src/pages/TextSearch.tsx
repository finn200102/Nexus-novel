import { useEffect, useState, useSyncExternalStore } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  onAccountStorageChange,
  storageGeneration,
} from "../services/accountStorage";
import apiClient, { getUserFacingError } from "../services/apiClient";
import { Banner, Button, Input, PageHeader } from "../components/ui";
type Match = {
  novel_id: number;
  novel_title: string;
  chapter_id: number;
  chapter_number: number;
  chapter_title: string;
  snippet: string;
  chapter_key: string;
  library_id: number;
};
function TextSearchContents() {
  const [params, setParams] = useSearchParams(),
    q = params.get("q") || "",
    novel = params.get("novel_id"),
    offset =
      Number.isSafeInteger(Number(params.get("offset"))) &&
      Number(params.get("offset")) >= 0
        ? Number(params.get("offset"))
        : 0;
  const [draft, setDraft] = useState(q),
    [result, setResult] = useState<{ total: number; matches: Match[] } | null>(
      null,
    ),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(false);
  useEffect(() => setDraft(q), [q]);
  useEffect(() => {
    if (q.trim().length < 2) {
      setResult(null);
      return;
    }
    setResult(null);
    const controller = new AbortController();
    setLoading(true);
    setError("");
    void apiClient
      .get("/chapter/search", {
        params: { q, novel_id: novel || undefined, offset, limit: 20 },
        signal: controller.signal,
      })
      .then((response) => {
        if (!controller.signal.aborted) setResult(response.data);
      })
      .catch((err) => {
        if (!controller.signal.aborted)
          setError(
            getUserFacingError(err, "Could not search downloaded text."),
          );
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [q, novel, offset]);
  const page = (value: number) =>
    setParams((previous) => {
      const next = new URLSearchParams(previous);
      next.set("offset", String(value));
      return next;
    });
  return (
    <div>
      <PageHeader
        title={novel ? "Search this book" : "Search downloaded text"}
        description="Search text downloaded to Nexus. Source pages and unavailable chapters are not included."
      />
      <form
        onSubmit={(event) => {
          event.preventDefault();
          const next = new URLSearchParams();
          if (novel) next.set("novel_id", novel);
          if (draft.trim()) next.set("q", draft.trim());
          setParams(next);
        }}
      >
        <Input
          label="Words in chapter text"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
        <Button type="submit" disabled={draft.trim().length < 2}>
          Search
        </Button>
      </form>
      {novel && (
        <Link to={`/search?q=${encodeURIComponent(q)}`}>
          Search all my downloaded books
        </Link>
      )}
      {loading && <p role="status">Searching…</p>}
      {error && <Banner tone="warning">{error}</Banner>}
      {!loading && !error && result && (
        <>
          <p role="status">{result.total} matches</p>
          <ul>
            {result.matches.map((match, index) => (
              <li key={`${match.chapter_id}:${index}`}>
                <Link
                  to={`/library/${match.library_id}/novels/${match.novel_id}/${match.chapter_number}?chapter_key=${encodeURIComponent(match.chapter_key)}`}
                >
                  {match.novel_title} · Chapter {match.chapter_number}:{" "}
                  {match.chapter_title}
                </Link>
                <p>{match.snippet}</p>
              </li>
            ))}
          </ul>
          <nav aria-label="Text search pages">
            <Button
              disabled={!offset}
              onClick={() => page(Math.max(0, offset - 20))}
            >
              Previous matches
            </Button>
            <Button
              disabled={offset + 20 >= result.total}
              onClick={() => page(offset + 20)}
            >
              Next matches
            </Button>
          </nav>
        </>
      )}
    </div>
  );
}

export default function TextSearch() {
  const generation = useSyncExternalStore(
    onAccountStorageChange,
    storageGeneration,
  );
  const [params] = useSearchParams();
  return <TextSearchContents key={`${generation}:${params.toString()}`} />;
}
