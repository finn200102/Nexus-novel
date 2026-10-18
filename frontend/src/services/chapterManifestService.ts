import apiClient from './apiClient';
import { accountStorage, accountStorageKey } from './accountStorage';
import type { ChapterIdentity } from './chapterIdentity';
import type {ManifestStateItem,ManifestStatePage,ChapterManifestMapping,ManifestPreviewInput as WirePreviewInput,ManifestRemoteChoice,ManifestReviewItem,ManifestReviewView,ManifestOperationResponse} from '../generated/api';
export type ManifestChapter=ManifestStateItem;
export type ManifestState=ManifestStatePage;
export type ManifestMapping=Required<ChapterManifestMapping>;
export type ManifestPreviewInput=Omit<WirePreviewInput,'mappings'>&{mappings:ManifestMapping[]};
export type RemoteChoice=ManifestRemoteChoice;
export type ManifestItem=ManifestReviewItem;
export type ManifestPage<T>={items:T[];total:number;offset:number;limit:number;has_more:boolean};
export type ManifestReview=ManifestReviewView;
export type ManifestIntent={action:'apply';review_id:number;body:{review_token:string;operation_id:string}}|{action:'undo';review_id:number;body:{expected_revision:number;expected_manifest_epoch:string;expected_manifest_revision:string;operation_id:string}};
const base=(novelId:number)=>`/chapter/novel/${novelId}/manifest`;
const config=(signal?:AbortSignal)=>({signal,headers:{'Cache-Control':'no-cache'}});
export const chapterManifestService={
 state:async(novelId:number,cursor?:string,expected?:Pick<ChapterIdentity,'manifest_epoch'|'manifest_revision'>,signal?:AbortSignal):Promise<ManifestState> => (await apiClient.get(base(novelId)+'-state',{...config(signal),params:{limit:100,cursor,...(expected?{expected_manifest_epoch:expected.manifest_epoch,expected_manifest_revision:expected.manifest_revision}:{})}})).data,
 preview:async(novelId:number,input:ManifestPreviewInput,signal?:AbortSignal):Promise<ManifestReview> => (await apiClient.post(base(novelId)+'/preview',input,config(signal))).data,
 history:async(novelId:number,offset=0,signal?:AbortSignal):Promise<ManifestPage<ManifestReview>> => (await apiClient.get(base(novelId)+'/reviews',{...config(signal),params:{offset,limit:10}})).data,
 review:async(novelId:number,id:number,signal?:AbortSignal):Promise<ManifestReview> => (await apiClient.get(base(novelId)+`/reviews/${id}`,config(signal))).data,
 items:async(novelId:number,id:number,kind:'items'|'unmapped',offset=0,signal?:AbortSignal):Promise<ManifestPage<ManifestItem>> => (await apiClient.get(base(novelId)+`/reviews/${id}/items`,{...config(signal),params:{kind,offset,limit:50}})).data,
 remote:async(novelId:number,id:number,q='',offset=0,signal?:AbortSignal):Promise<ManifestPage<RemoteChoice>> => (await apiClient.get(base(novelId)+`/reviews/${id}/remote`,{...config(signal),params:{q,offset,limit:20}})).data,
 execute:async(novelId:number,intent:ManifestIntent):Promise<ManifestOperationResponse> => (await apiClient.post(base(novelId)+(intent.action==='apply'?'/apply':`/reviews/${intent.review_id}/undo`),intent.body)).data,
};
const key=(novelId:number)=>`chapter-manifest-intent:${novelId}`;
export function loadManifestIntent(novelId:number):ManifestIntent|null {
 try{const value=JSON.parse(accountStorage.getItem(key(novelId))||'null');if(!value || !['apply','undo'].includes(value.action)||!Number.isSafeInteger(value.review_id)||value.review_id<1||typeof value.body?.operation_id!=='string'||!value.body.operation_id||value.body.operation_id.length>128)return null;
 if(value.action==='apply'&&(typeof value.body.review_token!=='string'||!value.body.review_token||value.body.review_token.length>4096))return null;
 if(value.action==='undo'&&(!Number.isSafeInteger(value.body.expected_revision)||value.body.expected_revision<1||typeof value.body.expected_manifest_epoch!=='string'||!/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(value.body.expected_manifest_epoch)||typeof value.body.expected_manifest_revision!=='string'||!/^(0|[1-9]\d{0,18})$/.test(value.body.expected_manifest_revision)))return null;
 return value;}catch{return null;}
}
export function saveManifestIntent(novelId:number,value:ManifestIntent|null){if(value)accountStorage.setItem(key(novelId),JSON.stringify(value));else accountStorage.removeItem(key(novelId));}
export function hasPendingManifestIntents():boolean{try{const prefix=accountStorageKey('chapter-manifest-intent:');return Object.keys(localStorage).some(value=>value.startsWith(prefix)&&loadManifestIntent(Number(value.slice(prefix.length)))!==null);}catch{return false;}}
