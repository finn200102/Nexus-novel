import { SlidersHorizontal } from "lucide-react";
import { Button, InputChip, Select } from "../ui";
import type { DiscoveryFilters } from "../../types/discovery";
import type { DiscoveryFilterChip } from "../../services/discoveryFilters";
import { COMMON_GENRES, LENGTHS, lengthValue } from "./discoverOptions";

const SORTS = [
  { value: "updated:desc", label: "Recently updated" },
  { value: "favorites:desc", label: "Most favourites" },
  { value: "follows:desc", label: "Most follows" },
  { value: "views:desc", label: "Most views" },
  { value: "reviews:desc", label: "Most reviews" },
  { value: "word_count:desc", label: "Longest" },
  { value: "word_count:asc", label: "Shortest" },
  { value: "chapter_count:desc", label: "Most chapters" },
  { value: "title:asc", label: "Title A–Z" },
];

const STATUSES = [
  { value: "", label: "Any status" },
  { value: "Ongoing", label: "Ongoing" },
  { value: "In-Progress", label: "In progress" },
  { value: "Complete", label: "Complete" },
];

const UPDATED = [
  { value: "", label: "Updated any time" },
  { value: "7", label: "Updated this week" },
  { value: "30", label: "Updated this month" },
  { value: "90", label: "Updated in 3 months" },
  { value: "365", label: "Updated this year" },
];

interface FilterBarProps {
  filters: DiscoveryFilters;
  /** Apply a change immediately. */
  onChange: (patch: Partial<DiscoveryFilters>) => void;
  onMoreFilters: () => void;
  moreOpen: boolean;
  chips: DiscoveryFilterChip[];
  onRemoveChip: (chip: DiscoveryFilterChip) => void;
  onClearAll: () => void;
  onSaveSearch?: () => void;
}

/** Five inline filters (Sort, Status, Length, Updated, Genre), More filters, and the active filter chips. */
export function FilterBar({ filters, onChange, onMoreFilters, moreOpen, chips, onRemoveChip, onClearAll, onSaveSearch }: FilterBarProps) {
  const sort = `${filters.sortBy || "updated"}:${filters.sortOrder || "desc"}`;
  const sortOptions = SORTS.some((option) => option.value === sort) ? SORTS : [...SORTS, { value: sort, label: "Custom order" }];
  const length = lengthValue(filters);
  const genre = filters.genre.length === 1 ? filters.genre[0] : filters.genre.length > 1 ? "__several" : "";
  const genreOptions = [
    { value: "", label: "Any genre" },
    ...(filters.genre.length > 1 ? [{ value: "__several", label: `${filters.genre.length} genres` }] : []),
    ...(genre && genre !== "__several" && !COMMON_GENRES.includes(genre) ? [{ value: genre, label: genre }] : []),
    ...COMMON_GENRES.map((name) => ({ value: name, label: name })),
  ];

  return (
    <div className="discover-filterbar">
      <div className="discover-filterbar__row" role="group" aria-label="Filters">
        <Select
          label="Sort"
          hideLabel
          value={sort}
          options={sortOptions}
          onChange={(event) => {
            const [sortBy, sortOrder] = event.target.value.split(":");
            onChange({ sortBy, sortOrder });
          }}
        />
        <Select label="Status" hideLabel value={filters.status} options={STATUSES} onChange={(event) => onChange({ status: event.target.value })} />
        <Select
          label="Length"
          hideLabel
          value={length}
          options={[...LENGTHS.map(({ value, label }) => ({ value, label })), ...(length === "custom" ? [{ value: "custom", label: "Custom length" }] : [])]}
          onChange={(event) => {
            const preset = LENGTHS.find((option) => option.value === event.target.value);
            if (preset) onChange({ minWordCount: preset.min, maxWordCount: preset.max });
          }}
        />
        <Select label="Updated" hideLabel value={filters.updatedSinceDays} options={UPDATED} onChange={(event) => onChange({ updatedSinceDays: event.target.value })} />
        <Select
          label="Genre"
          hideLabel
          value={genre}
          options={genreOptions}
          onChange={(event) => {
            if (event.target.value === "__several") return;
            onChange({ genre: event.target.value ? [event.target.value] : [] });
          }}
        />
        <Button
          variant="secondary"
          icon={<SlidersHorizontal aria-hidden="true" />}
          aria-haspopup="dialog"
          aria-expanded={moreOpen}
          onClick={onMoreFilters}
        >
          More filters{chips.length > 0 ? ` (${chips.length})` : ""}
        </Button>
      </div>
      {chips.length > 0 && (
        <div className="discover-filterbar__chips">
          <ul aria-label="Active filters">
            {chips.map((chip) => (
              <li key={`${chip.key}-${chip.value ?? ""}`}>
                <InputChip onRemove={() => onRemoveChip(chip)} removeLabel={`Remove filter ${chip.label}`}>{chip.label}</InputChip>
              </li>
            ))}
          </ul>
          <Button size="sm" variant="ghost" onClick={onClearAll}>Clear all</Button>
          {onSaveSearch && <Button size="sm" variant="ghost" onClick={onSaveSearch}>Save search</Button>}
        </div>
      )}
    </div>
  );
}

export default FilterBar;
