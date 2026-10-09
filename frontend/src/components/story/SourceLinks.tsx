import { buildSourceLinks, type SourceLink } from "../../lib/sourceLinks";

interface SourceLinksProps {
  site: string | null;
  url: string | null;
  storyId?: number | string | null;
}

const ExternalLink = ({ link }: { link: SourceLink }) => (
  <a
    className="ui-button ui-button--ghost"
    href={link.href}
    target="_blank"
    rel="noopener noreferrer"
  >
    {link.label}
    <span className="visually-hidden"> (opens in a new tab)</span>
  </a>
);

/** External links from the story page to its original source: open, comments, kudos. */
export default function SourceLinks({ site, url, storyId }: SourceLinksProps) {
  const links = buildSourceLinks({ site, url, storyId });
  if (!links) return null;
  const items = [links.open, links.comments, links.kudos].filter((link): link is SourceLink => link !== null);
  if (items.length === 0) return null;

  return (
    <nav className="source-links" aria-label={`Links on ${links.siteName}`}>
      {items.map((link) => (
        <ExternalLink key={link.label} link={link} />
      ))}
    </nav>
  );
}
