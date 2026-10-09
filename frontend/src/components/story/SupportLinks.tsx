import { SUPPORT_KIND_LABELS, safeSupportLinks, type SupportLink } from "../../lib/supportLinks";

interface SupportLinksProps {
  links: SupportLink[] | null | undefined;
}

const HeartIcon = () => (
  <svg className="support-links__icon" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" focusable="false">
    <path
      d="M12 21s-7.5-4.6-9.6-9.1C1 8.6 2.9 5 6.4 5c2 0 3.4 1.1 4.1 2.3C11.2 6.1 12.6 5 14.6 5c3.5 0 5.4 3.6 4 6.9C19.5 16.4 12 21 12 21z"
      fill="currentColor"
    />
  </svg>
);

/** "Support the author" chips linking to the creator's platform pages. */
export default function SupportLinks({ links }: SupportLinksProps) {
  const safe = safeSupportLinks(links);
  if (safe.length === 0) return null;

  return (
    <nav className="source-links support-links" aria-label="Support the author">
      <span className="support-links__heading">Support the author</span>
      {safe.map((link) => (
        <a
          key={link.url}
          className="ui-button ui-button--ghost"
          href={link.url}
          target="_blank"
          rel="noopener noreferrer"
        >
          <HeartIcon />
          {SUPPORT_KIND_LABELS[link.kind]}
          <span className="visually-hidden"> (opens in a new tab)</span>
        </a>
      ))}
    </nav>
  );
}
