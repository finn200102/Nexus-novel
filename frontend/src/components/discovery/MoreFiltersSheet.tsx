import { Button, Input, SegmentedControl, Select, Sheet, Switch } from "../ui";
import { ChipInput } from "../common/ChipInput";
import type { DiscoveryFilters } from "../../types/discovery";

const LANGUAGE_SUGGESTIONS = ["English", "French", "German", "Spanish", "Italian", "Portuguese", "Russian", "Chinese", "Japanese", "Korean"];

type ListKey = { [K in keyof DiscoveryFilters]: DiscoveryFilters[K] extends string[] ? K : never }[keyof DiscoveryFilters];
type ScalarKey = Exclude<keyof DiscoveryFilters, ListKey>;

interface MoreFiltersSheetProps {
  open: boolean;
  onClose: () => void;
  /** Draft filters edited in the sheet; applied with Apply. */
  filters: DiscoveryFilters;
  onChange: (filters: DiscoveryFilters) => void;
  onApply: () => void;
  onReset: () => void;
  fandomSuggestions: string[];
  onFandomDraftChange: (draft: string) => void;
}

/** "More filters": Content, Numbers, Language and crossovers, Exclude (proposal §3.2). */
export function MoreFiltersSheet({ open, onClose, filters, onChange, onApply, onReset, fandomSuggestions, onFandomDraftChange }: MoreFiltersSheetProps) {
  const setList = (key: ListKey, values: string[]) => onChange({ ...filters, [key]: values });
  const setValue = (key: ScalarKey, value: string) => onChange({ ...filters, [key]: value });
  const number = (key: ScalarKey, label: string, placeholder = "0") => (
    <Input label={label} type="number" min={0} inputMode="numeric" value={filters[key] as string} placeholder={placeholder} onChange={(event) => setValue(key, event.target.value)} />
  );

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="More filters"
      className="discover-more"
      footer={
        <div className="discover-more__footer">
          <Button variant="ghost" onClick={onReset}>Reset</Button>
          <Button variant="primary" onClick={onApply}>Show results</Button>
        </div>
      }
    >
      <div className="discover-more__body">
        <section aria-labelledby="discover-more-content" className="discover-more__group">
          <h3 id="discover-more-content">Content</h3>
          <ChipInput label="Fandom or series" values={filters.fandom} onChange={(values) => setList("fandom", values)} onDraftChange={onFandomDraftChange} suggestions={fandomSuggestions} placeholder="Type a fandom, then Enter" />
          <ChipInput label="Tags" values={filters.tag} onChange={(values) => setList("tag", values)} placeholder="For example: time loop" />
          <ChipInput label="Genres" values={filters.genre} onChange={(values) => setList("genre", values)} placeholder="For example: fantasy" />
          <SegmentedControl
            label="Match tags, genres and fandoms"
            value={(filters.tagMode || "all") as "all" | "any"}
            onChange={(value) => setValue("tagMode", value)}
            options={[
              { value: "all", label: "All of these" },
              { value: "any", label: "Any of these" },
            ]}
          />
          <Input label="My label" value={filters.label} placeholder="For example: cozy" onChange={(event) => setValue("label", event.target.value)} />
        </section>

        <section aria-labelledby="discover-more-numbers" className="discover-more__group">
          <h3 id="discover-more-numbers">Numbers</h3>
          <div className="discover-more__grid">
            {number("minWordCount", "Min words")}
            {number("maxWordCount", "Max words", "No maximum")}
            {number("minChapterCount", "Min chapters")}
            {number("minFavorites", "Min favourites")}
            {number("minFollows", "Min follows")}
            {number("minReviews", "Min reviews")}
          </div>
        </section>

        <section aria-labelledby="discover-more-language" className="discover-more__group">
          <h3 id="discover-more-language">Language and crossovers</h3>
          <ChipInput label="Language" values={filters.language} onChange={(values) => setList("language", values)} suggestions={LANGUAGE_SUGGESTIONS} placeholder="For example: English" />
          <Select
            label="Crossovers"
            value={filters.crossover}
            onChange={(event) => setValue("crossover", event.target.value)}
            options={[
              { value: "", label: "Any" },
              { value: "true", label: "Crossovers only" },
              { value: "false", label: "Single fandom only" },
            ]}
          />
          <Switch label="Complete stories only" checked={filters.completeOnly === "true"} onChange={(checked) => setValue("completeOnly", checked ? "true" : "")} />
        </section>

        <section aria-labelledby="discover-more-exclude" className="discover-more__group">
          <h3 id="discover-more-exclude">Exclude</h3>
          <p className="text-secondary text-sm">Hide any story that matches. Tags, genres, fandoms and authors must match exactly; words match the title or summary.</p>
          <ChipInput tone="exclude" label="Tags" values={filters.excludeTag} onChange={(values) => setList("excludeTag", values)} placeholder="For example: character death" />
          <ChipInput tone="exclude" label="Fandoms" values={filters.excludeFandom} onChange={(values) => setList("excludeFandom", values)} suggestions={fandomSuggestions} placeholder="Fandom name" />
          <ChipInput tone="exclude" label="Genres" values={filters.excludeGenre} onChange={(values) => setList("excludeGenre", values)} placeholder="For example: horror" />
          <ChipInput tone="exclude" label="Authors" values={filters.excludeAuthor} onChange={(values) => setList("excludeAuthor", values)} placeholder="Author name" />
          <ChipInput tone="exclude" label="Words in title or summary" values={filters.excludeText} onChange={(values) => setList("excludeText", values)} placeholder="For example: gore" />
        </section>
      </div>
    </Sheet>
  );
}

export default MoreFiltersSheet;
