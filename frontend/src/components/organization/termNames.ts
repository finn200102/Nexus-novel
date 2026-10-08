export type TermLike = string | { name?: string | null } | null | undefined;

/** Distinct, trimmed names from metadata terms that are either strings or {name} objects. */
export const termNames = (terms: TermLike[] | null | undefined): string[] => {
  const names = (terms ?? []).map((term) => (typeof term === "string" ? term : term?.name ?? "")).map((name) => name.trim());
  return Array.from(new Set(names.filter(Boolean)));
};
