import apiClient from './apiClient';
import {accountStorage,accountStorageKey} from './accountStorage';
import type {ExportChapterReference,ImportReadingCandidate,ImportReadingReviewView,ImportReadingMapping,ImportReadingPreview,ImportReadingReviewPage,ImportReadingChapterPage} from '../generated/api';
export type ImportReference=ExportChapterReference;
export type ImportCandidate=ImportReadingCandidate;
export type ImportReview=Omit<ImportReadingReviewView,'items'> & {items:Array<ImportReadingReviewView['items'][number] & {archived_body_available?:boolean;retained_originals?:number;backup_placeholder_key?:string|null}>};
export type ImportMapping=Required<ImportReadingMapping> & {restore_archived_content?:boolean};
export type ImportPreview=ImportReadingPreview;
export type ImportIntent={review_id:number;body:{review_token:string;operation_id:string}};
const base='/me/import-reading-reviews';
const config=(signal?:AbortSignal)=>({signal,headers:{'Cache-Control':'no-cache'}});
export const importReadingService={
 list:async(offset=0,signal?:AbortSignal):Promise<ImportReadingReviewPage> =>(await apiClient.get(base,{...config(signal),params:{offset,limit:10}})).data,
 get:async(id:number,offset=0,signal?:AbortSignal):Promise<ImportReview> =>(await apiClient.get(`${base}/${id}`,{...config(signal),params:{offset,limit:100}})).data,
 chapters:async(id:number,q='',offset=0,signal?:AbortSignal):Promise<ImportReadingChapterPage> =>(await apiClient.get(`${base}/${id}/chapters`,{...config(signal),params:{q,offset,limit:20}})).data,
 preview:async(id:number,revision:number,mappings:ImportMapping[],keepExistingPlace=false):Promise<ImportPreview> =>(await apiClient.post(`${base}/${id}/preview`,{expected_revision:revision,mappings,keep_existing_place:keepExistingPlace})).data,
 apply:async(intent:ImportIntent):Promise<unknown> =>(await apiClient.post(`${base}/${intent.review_id}/apply`,intent.body)).data,
};
const key='import-reading-intent';
export function loadImportReadingIntent():ImportIntent|null{try{const value=JSON.parse(accountStorage.getItem(key)||'null');return value&&Number.isSafeInteger(value.review_id)&&value.review_id>0&&typeof value.body?.review_token==='string'&&value.body.review_token.length>0&&value.body.review_token.length<=128&&typeof value.body?.operation_id==='string'&&value.body.operation_id.length>0&&value.body.operation_id.length<=128?value:null;}catch{return null;}}
export function saveImportReadingIntent(value:ImportIntent|null){if(value)accountStorage.setItem(key,JSON.stringify(value));else accountStorage.removeItem(key);}
export function hasPendingImportReadingIntent(){return !!loadImportReadingIntent();}
export const importReadingIntentKey=()=>accountStorageKey(key);
