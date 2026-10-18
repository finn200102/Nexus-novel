import apiClient from "./apiClient";
import type { OwnedLibraryDefinition as WireDefinition, LibraryStoryItem, LibraryStoryPage, LibraryViewOptions as WireOptions } from "../generated/api";
export type OwnedLibraryDefinition = Required<WireDefinition>;
export type LibrarySortBy = OwnedLibraryDefinition["sort_by"];
export type FollowState = OwnedLibraryDefinition["follow_states"][number];
export type LibraryViewItem = LibraryStoryItem;
export type LibraryViewPage = LibraryStoryPage;
export type LibraryViewOptions = WireOptions;
export const defaultLibraryDefinition = (libraryIds: number[] = []): OwnedLibraryDefinition => ({ version:1,scope:"owned_library",library_ids:libraryIds,q:"",source:null,follow_states:[],user_tag:null,min_rating:null,shelf_id:null,sort_by:"recent" });
export const libraryViewService = {
  preview: async (definition: OwnedLibraryDefinition, offset = 0, limit = 50, signal?: AbortSignal): Promise<LibraryViewPage> =>
    (await apiClient.post("/library-views/preview", {definition,offset,limit},{signal})).data,
  options: async (signal?: AbortSignal): Promise<LibraryViewOptions> => (await apiClient.get("/library-views/options",{signal})).data,
};

/** Compare normalized wire definitions without relying on object key or selection order. */
export function ownedDefinitionKey(value: OwnedLibraryDefinition): string {
  return JSON.stringify([value.version,value.scope,[...value.library_ids].sort((a,b)=>a-b),value.q,value.source,value.follow_states.slice().sort(),value.user_tag?.trim()||null,value.min_rating,value.shelf_id,value.sort_by]);
}
