import apiClient from "./apiClient";
import { DiscoveryFilters } from "../types/discovery";
import type * as contracts from "../generated/api";

export type SavedSearch = Omit<contracts.SavedSearchResponse, "filters" | "definition"> & {
  filters: Partial<DiscoveryFilters>;
  definition: SavedSearchDefinition | null;
};

export type SavedSearchDefinition = Omit<Required<contracts.SavedSearchDefinition>, "filters" | "canonical_include" | "canonical_exclude"> & Pick<contracts.SavedSearchDefinition, "canonical_include" | "canonical_exclude"> & {
  filters: DiscoveryFilters;
};
/** Canonical identities have a versioned top-level wire contract, never raw labels. */
export function savedSearchFilters(definition: SavedSearchDefinition): DiscoveryFilters {
  return { ...definition.filters, canonicalInclude: definition.filters.canonicalInclude ?? definition.canonical_include ?? [], canonicalExclude: definition.filters.canonicalExclude ?? definition.canonical_exclude ?? [] };
}
export function makeSavedSearchDefinition(definition: SavedSearchDefinition): SavedSearchDefinition {
  const { canonicalInclude, canonicalExclude, ...filters } = savedSearchFilters(definition);
  const include = [...new Set(canonicalInclude ?? [])], exclude = [...new Set(canonicalExclude ?? [])];
  if (include.length || exclude.length || definition.version === 2) return { ...definition, version: 2, filters, canonical_include: include, canonical_exclude: exclude };
  const { canonical_include: _include, canonical_exclude: _exclude, ...legacy } = definition;
  void _include; void _exclude;
  return { ...legacy, version: 1, filters };
}

export function savedSearchHref(definition: SavedSearchDefinition): string {
  const params = new URLSearchParams({ filters: JSON.stringify(savedSearchFilters(definition)) });
  if (definition.q) params.set("q", definition.q);
  if (definition.similar_to !== null) params.set("similar_to", String(definition.similar_to));
  return `/discover/${encodeURIComponent(definition.site ?? "all")}?${params.toString()}`;
}

export const savedSearchService = {
  async list(): Promise<SavedSearch[]> {
    return (await apiClient.get("/saved-searches")).data;
  },
  async create(name: string, definition: SavedSearchDefinition): Promise<SavedSearch> {
    return (await apiClient.post("/saved-searches", {
      name,
      definition: makeSavedSearchDefinition(definition),
      notify_on_match: false,
    })).data;
  },
  async update(saved: SavedSearch, name: string, definition: SavedSearchDefinition): Promise<SavedSearch> {
    return (await apiClient.put(`/saved-searches/${saved.id}`, { name, definition: makeSavedSearchDefinition(definition), expected_revision: saved.revision, notify_on_match: false })).data;
  },
  async remove(saved: SavedSearch) {
    await apiClient.delete(`/saved-searches/${saved.id}`, { params: { expected_revision: saved.revision } });
  },
};

export type CatalogWatchState = contracts.WatchState;
export type CatalogWatchMode = NonNullable<CatalogWatchState["mode"]>;
export type CatalogShelfPage = contracts.CatalogResultPage;
export type CatalogMatch = contracts.CatalogMatchItem;
export type CatalogMatchesPage = contracts.CatalogMatchPage;
export const catalogWatchService = {
  state:async(id:number,signal?:AbortSignal):Promise<CatalogWatchState>=>(await apiClient.get(`/catalog-watches/${id}`,{signal})).data,
  prepare:async(saved:SavedSearch,mode:CatalogWatchMode):Promise<CatalogWatchState>=>(await apiClient.post(`/catalog-watches/${saved.id}/prepare`,{expected_revision:saved.revision,mode} satisfies contracts.PrepareWatch)).data,
  activate:async(saved:SavedSearch,preparedRevision:string):Promise<CatalogWatchState>=>(await apiClient.post(`/catalog-watches/${saved.id}/activate`,{expected_revision:saved.revision,prepared_revision:preparedRevision} satisfies contracts.ActivateWatch)).data,
  pause:async(saved:SavedSearch,watchRevision:string):Promise<CatalogWatchState>=>(await apiClient.post(`/catalog-watches/${saved.id}/pause`,{expected_revision:saved.revision,watch_revision:watchRevision} satisfies contracts.PauseWatch)).data,
  results:async(id:number,offset=0,limit=50,signal?:AbortSignal):Promise<CatalogShelfPage>=>(await apiClient.post(`/catalog-watches/${id}/results`,{offset,limit} satisfies contracts.WatchPageInput,{signal})).data,
  matches:async(id:number,offset=0,limit=50,signal?:AbortSignal):Promise<CatalogMatchesPage>=>(await apiClient.get(`/catalog-watches/${id}/matches`,{params:{offset,limit},signal})).data,
  read:async(id:number,matchId:number,watchRevision:string):Promise<contracts.MatchReadResult>=>(await apiClient.post(`/catalog-watches/${id}/matches/${matchId}/read`,{watch_revision:watchRevision} satisfies contracts.ReadMatch)).data,
};
