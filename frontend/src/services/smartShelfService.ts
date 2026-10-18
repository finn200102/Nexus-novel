import apiClient from "./apiClient";
import type { SmartShelfResponse, SmartShelfResults as WireResults } from "../generated/api";
import type { OwnedLibraryDefinition } from "./libraryViewService";
export type SmartShelf = Omit<SmartShelfResponse,"definition"> & {definition:OwnedLibraryDefinition|null};
export type SmartShelfResults = WireResults;
export const smartShelfService = {
  list: async (signal?:AbortSignal):Promise<SmartShelf[]> => (await apiClient.get("/smart-shelves",{signal})).data,
  create: async (name:string,definition:OwnedLibraryDefinition):Promise<SmartShelf> => (await apiClient.post("/smart-shelves",{name,definition})).data,
  update: async (id:number,name:string,definition:OwnedLibraryDefinition,revision:string):Promise<SmartShelf> => (await apiClient.put(`/smart-shelves/${id}`,{name,definition,expected_revision:revision})).data,
  remove: async (id:number,revision:string):Promise<void> => { await apiClient.delete(`/smart-shelves/${id}`,{params:{expected_revision:revision}}); },
  results: async (id:number,offset=0,limit=50,signal?:AbortSignal):Promise<SmartShelfResults> => (await apiClient.post(`/smart-shelves/${id}/results`,{offset,limit},{signal})).data,
};
