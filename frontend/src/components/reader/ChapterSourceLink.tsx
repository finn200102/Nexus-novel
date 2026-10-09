import { chapterSourceLabel } from "../../lib/sourceLinks";

interface ChapterSourceLinkProps {
  site: string | null;
  /** The chapter's original URL on the source site. */
  href: string | null;
}

/** End-of-chapter link to read the chapter on its original site. */
export default function ChapterSourceLink({ site, href }: ChapterSourceLinkProps) {
  const label = chapterSourceLabel(site);
  if (!href || !label) return null;
  return (
    <p className="reader-end__source">
      <a className="ui-button ui-button--ghost" href={href} target="_blank" rel="noopener noreferrer">
        {label}
        <span className="visually-hidden"> (opens in a new tab)</span>
      </a>
    </p>
  );
}
