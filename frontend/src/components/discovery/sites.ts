/** Sites Discover can browse; `value` is the `/discover/:site` segment. */
export const DISCOVER_SITES = [
  { value: "all", label: "All sites" },
  { value: "royalroad", label: "Royal Road" },
  { value: "archive", label: "AO3" },
  { value: "fanfiction", label: "FanFiction.Net" },
  { value: "spacebattles", label: "SpaceBattles" },
  { value: "sufficientvelocity", label: "Sufficient Velocity" },
  { value: "questionablequesting", label: "Questionable Questing" },
  { value: "webnovel", label: "WebNovel" },
  { value: "scribblehub", label: "Scribble Hub (experimental)" },
];

export const discoverSiteLabel = (value: string) =>
  DISCOVER_SITES.find((site) => site.value === value)?.label ?? value;
