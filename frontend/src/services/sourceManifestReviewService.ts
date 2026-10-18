import apiClient from './apiClient';
import {accountStorage} from './accountStorage';
import type {SourceManifestHead,SourceManifestReviewContext,SourceManifestReviewView,SourceManifestReviewPage,SourceManifestReviewPreviewInput,SourceManifestReviewAction,SourceManifestReviewResult} from '../generated/api';
export type LifecycleContext=SourceManifestReviewContext;
export type LifecycleReview=SourceManifestReviewView;
export type LifecycleInput=SourceManifestReviewPreviewInput;
export type LifecycleIntent={id:string;action:'apply'|'undo';input:SourceManifestReviewAction;acknowledged?:boolean};
const prefix='/admin/source-manifest-reviews',intentKey='source-lifecycle-review-intent';
export function lifecycleIntent():LifecycleIntent|null {try {const value=JSON.parse(accountStorage.getItem(intentKey)||'null');if(typeof value?.id==='string'&&['apply','undo'].includes(value.action)&&Number.isSafeInteger(value.input?.expected_revision)&&value.input.expected_revision>0&&typeof value.input?.operation_id==='string')return value;}catch{/* Invalid local state cannot authorize an action. */}return null;}
export function saveLifecycleIntent(value:LifecycleIntent|null){if(value)accountStorage.setItem(intentKey,JSON.stringify(value));else accountStorage.removeItem(intentKey);}
export const hasPendingLifecycleIntent=()=>lifecycleIntent()!==null;
export const sourceManifestReviewService={
 head:async(id:number,signal?:AbortSignal):Promise<SourceManifestHead>=>(await apiClient.get(`${prefix}/novels/${id}/head`,{signal})).data,
 context:async(id:number,capture:string,offset=0,header?:{manifest_key:string;revision:string},signal?:AbortSignal):Promise<LifecycleContext>=>(await apiClient.get(`${prefix}/novels/${id}/context`,{params:{capture_id:capture,offset,limit:50,expected_manifest_key:header?.manifest_key,expected_revision:header?.revision},signal})).data,
 preview:async(input:LifecycleInput):Promise<LifecycleReview>=>(await apiClient.post(`${prefix}/preview`,input,{params:{offset:0,limit:50}})).data,
 get:async(id:string,offset=0):Promise<LifecycleReview>=>(await apiClient.get(`${prefix}/${encodeURIComponent(id)}`,{params:{offset,limit:50}})).data,
 list:async(offset=0):Promise<SourceManifestReviewPage>=>(await apiClient.get(prefix,{params:{offset,limit:20}})).data,
 decide:async(intent:LifecycleIntent):Promise<SourceManifestReviewResult>=>(await apiClient.post(`${prefix}/${encodeURIComponent(intent.id)}/${intent.action}`,intent.input)).data,
};
