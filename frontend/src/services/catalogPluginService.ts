import apiClient from "./apiClient";
import type {CatalogCreateResponse,CatalogControlRequest,CatalogRebindRequest,CreateCatalogRequest,UpdateCatalogRequest,CatalogActiveJobsResponse} from "../generated/api";
import { accountStorage } from "./accountStorage";
import type { CatalogDefinition, CatalogJob, CatalogPreview, CatalogSourceCapability } from "./catalogScrapeService";
export type PluginCatalogCapability = CatalogSourceCapability & { site:string; persisted_site?:string; plugin_id:string; plugin_version:string; plugin_digest:string; definition_revision?:string };
export type PluginCatalogQuery = { version:2;mode:"newest"|"search";intent:"newest"|"search";run_mode:"scheduled_check"|"backfill";limit:number;max_pages:number;max_pages_per_run:number;daily_request_budget:number;source_options:{plugin_id:string;plugin_version:string;plugin_digest:string;operation:"listings"|"search";query?:string};min_words?:number;max_words?:number;status?:string;include_tags?:string[];exclude_tags?:string[];include_genres?:string[];exclude_genres?:string[] };
export type PluginCatalogDefinition = Omit<CatalogDefinition,"query"> & {query:PluginCatalogQuery;definition_revision:string;plugin_state:"ready"|"review_required"|"unavailable";plugin_reason?:string|null};
export type PluginCatalogPreview = Omit<CatalogPreview,"query"> & {query:PluginCatalogQuery;review_token:string};
export type PluginControl = Required<Pick<CatalogControlRequest,"expected_revision"|"operation_id">> & {expected_revision:string;operation_id:string};
export type PluginCreate = Pick<CreateCatalogRequest,"site"|"name"|"enabled"|"review_token"|"operation_id"|"schedule_interval_minutes"> & {site:string;query:PluginCatalogQuery;review_token:string;operation_id:string};
export type PluginRebind = Pick<CatalogRebindRequest,"expected_revision"|"operation_id"|"review_token"> & {query:PluginCatalogQuery};
export type PluginUpdate = Pick<UpdateCatalogRequest,"schedule"|"schedule_interval_minutes"|"name"|"enabled"> & PluginRebind;
export type PluginCatalogIntent = {kind:"create";body:PluginCreate;acknowledged_id?:number}|{kind:"update";id:number;body:PluginUpdate;acknowledged_id?:number}|{kind:"rebind";id:number;body:PluginRebind;acknowledged_id?:number}|{kind:"pause"|"resume"|"run"|"delete";id:number;body:PluginControl;acknowledged_id?:number};
const key="catalog-plugin-operation";
export function loadPluginCatalogIntent():PluginCatalogIntent|null{try{const value=JSON.parse(accountStorage.getItem(key)||"null");if(!value||!["create","update","rebind","pause","resume","run","delete"].includes(value.kind)||typeof value.body?.operation_id!=="string"||value.body.operation_id.length>128)return null;if(value.kind!=="create"&&(!Number.isSafeInteger(value.id)||value.id<1||!/^[0-9a-f]{64}$/.test(value.body.expected_revision)))return null;return value;}catch{return null;}}
export function savePluginCatalogIntent(value:PluginCatalogIntent|null){if(value)accountStorage.setItem(key,JSON.stringify(value));else accountStorage.removeItem(key);}
export const catalogPluginService={
 preview:async(site:string,query:PluginCatalogQuery):Promise<PluginCatalogPreview>=>(await apiClient.post("/catalog-scrapes/preview",{site,query},{timeout:13500})).data,
 create:async(body:PluginCreate):Promise<Pick<CatalogCreateResponse,"job"> & {definition:PluginCatalogDefinition}>=>(await apiClient.post("/catalog-scrapes",body)).data,
 activeJobs:async(id:number,offset=0,limit=50):Promise<CatalogActiveJobsResponse>=>(await apiClient.get(`/catalog-scrapes/${id}/active-jobs`,{params:{offset,limit}})).data,
 get:async(id:number):Promise<PluginCatalogDefinition>=>(await apiClient.get(`/catalog-scrapes/${id}`)).data,
 update:async(id:number,body:PluginUpdate):Promise<PluginCatalogDefinition>=>(await apiClient.patch(`/catalog-scrapes/${id}`,body)).data,
 rebind:async(id:number,body:PluginRebind):Promise<PluginCatalogDefinition>=>(await apiClient.post(`/catalog-scrapes/${id}/rebind`,body)).data,
 control:async(id:number,kind:"pause"|"resume"|"run"|"delete",body:PluginControl):Promise<PluginCatalogDefinition|CatalogJob|{deleted:boolean;id:number}>=>kind==="delete"?(await apiClient.delete(`/catalog-scrapes/${id}`,{data:body})).data:(await apiClient.post(`/catalog-scrapes/${id}/${kind}`,body)).data,
};

/** Validate the plugin-specific boundary without weakening built-in editor types. */
export function pluginCatalogDefinition(value:CatalogDefinition):PluginCatalogDefinition|null{
 const pins=value.query.source_options;
 if(!value.site.startsWith("plugin-")||!pins||typeof pins.plugin_id!=="string"||typeof pins.plugin_version!=="string"||typeof pins.plugin_digest!=="string"||!/^[a-f0-9]{64}$/.test(pins.plugin_digest)||!["listings","search"].includes(String(pins.operation))||!["newest","search"].includes(value.query.mode)||!value.definition_revision||!/^[a-f0-9]{64}$/.test(value.definition_revision)||!value.plugin_state)return null;
 const mode=value.query.mode as "newest"|"search";
 return {...value,definition_revision:value.definition_revision,plugin_state:value.plugin_state,query:{...value.query,version:2,mode,intent:mode,run_mode:value.query.run_mode??"scheduled_check",daily_request_budget:value.query.daily_request_budget??20,max_pages_per_run:value.query.max_pages_per_run??5,min_words:value.query.min_words??undefined,max_words:value.query.max_words??undefined,source_options:{...pins,plugin_id:pins.plugin_id,plugin_version:pins.plugin_version,plugin_digest:pins.plugin_digest,operation:pins.operation as "listings"|"search",...(typeof pins.query==="string"?{query:pins.query}:{})}}};
}
