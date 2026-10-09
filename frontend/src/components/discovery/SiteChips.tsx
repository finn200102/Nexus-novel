import { FilterChip } from "../ui";
import { DISCOVER_SITES } from "./sites";

interface SiteChipsProps {
  value: string;
  onChange: (site: string) => void;
}

/** "All sites" plus one chip per site (single choice; the selected chip shows a check). */
export function SiteChips({ value, onChange }: SiteChipsProps) {
  return (
    <div className="discover-sites" role="group" aria-label="Sites">
      {DISCOVER_SITES.map((site) => (
        <FilterChip key={site.value} selected={site.value === value} onChange={() => onChange(site.value)}>
          {site.label}
        </FilterChip>
      ))}
    </div>
  );
}

export default SiteChips;
