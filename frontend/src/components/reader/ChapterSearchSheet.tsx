import { useEffect, useMemo, useRef, useState } from "react";
import { Button, Input, Sheet, Switch } from "../ui";
import { prepareChapterSearch, type SearchBlock, type ChapterMatch } from "./chapterSearch";

export default function ChapterSearchSheet({ open, onClose, blocks, onJump }: {
  open: boolean; onClose: () => void; blocks: SearchBlock[]; onJump: (match: ChapterMatch) => void;
}) {
  const [query, setQuery] = useState("");
  const [caseSensitive, setCaseSensitive] = useState(false);
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const search = useMemo(() => prepareChapterSearch(open ? blocks : [], caseSensitive), [blocks, caseSensitive, open]);
  const result = useMemo(() => search(query), [search, query]);
  useEffect(() => { setActive(0); }, [query, caseSensitive, blocks]);
  const select = (delta: number) => setActive(value => (value + delta + result.matches.length) % Math.max(1, result.matches.length));
  return <Sheet open={open} onClose={onClose} title="Search this chapter" closeLabel="Close chapter search" initialFocus={input}>
    <p>Search the text in this reading view. Your query stays on this device.</p>
    <Input ref={input} label="Find text" search value={query} onClear={() => setQuery("")} maxLength={500} onChange={event => setQuery(event.target.value)}
      onKeyDown={event => {
        if (event.key === "ArrowDown" || event.key === "ArrowUp") { event.preventDefault(); select(event.key === "ArrowDown" ? 1 : -1); }
        if (event.key === "Enter" && result.matches[active]) { event.preventDefault(); onJump(result.matches[active]); }
      }} />
    <Switch label="Match case" checked={caseSensitive} onChange={setCaseSensitive} />
    {query.trim() && <p role="status">{result.truncated ? "First 200 matches. Refine your search for more." : `${result.matches.length} match${result.matches.length === 1 ? "" : "es"}.`}{result.matches.length ? ` Selected ${active + 1}.` : ""}</p>}
    {result.matches.length > 0 && <>
      <div className="reader-search-controls"><Button onClick={() => select(-1)}>Previous match</Button><Button onClick={() => select(1)}>Next match</Button><Button onClick={() => onJump(result.matches[active])}>Go to selected match</Button></div>
      <ol className="reader-search-results">{result.matches.map((match, index) => <li key={`${match.blockIndex}:${match.textOffset}`}>
        <button type="button" aria-current={index === active ? "true" : undefined} onClick={() => onJump(match)}>{index + 1}. {match.excerpt}</button>
      </li>)}</ol>
    </>}
  </Sheet>;
}
