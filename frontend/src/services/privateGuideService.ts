import apiClient from './apiClient';
import { accountStorage,accountStorageKey } from './accountStorage';
import type {GuideInput,GuidePreview,GuideArtifact,GuideJob,GuideState,GuideAction,GuideRetry} from '../generated/api';
// Explicit user choices remain required in the client, even where the wire has defaults.
export type PrivateGuideInput=Required<Pick<GuideInput,'provider_id'|'through_chapter'|'kind'|'external_consent'|'ao3_consent'>>&Omit<GuideInput,'provider_id'|'through_chapter'|'kind'|'external_consent'|'ao3_consent'>;
export type PrivateGuidePreview=GuidePreview;
export type PrivateGuideArtifact=GuideArtifact;
export type PrivateGuideJob=GuideJob;
export type PrivateGuideState=GuideState;
export type PrivateGuideIntent = {action:'create';body:PrivateGuideInput & {review_token:string;operation_id:string};acknowledged_id?:number}|{action:'cancel';id:number;body:GuideAction;acknowledged_id?:number}|{action:'retry';id:number;body:GuideRetry;acknowledged_id?:number};
const path=(novelId:number)=>`/reader/stories/${novelId}/guide`;
const config=(signal?:AbortSignal)=>({signal,headers:{'Cache-Control':'no-cache'}});
export const privateGuideService={
 state:async(novelId:number,signal?:AbortSignal,offset=0):Promise<PrivateGuideState>=>(await apiClient.get(path(novelId),{...config(signal),params:{offset,limit:20}})).data,
 preview:async(novelId:number,input:PrivateGuideInput,signal?:AbortSignal):Promise<PrivateGuidePreview>=>(await apiClient.post(path(novelId)+'/preview',input,config(signal))).data,
 job:async(novelId:number,id:number,signal?:AbortSignal):Promise<PrivateGuideJob>=>(await apiClient.get(path(novelId)+`/jobs/${id}`,config(signal))).data,
 execute:async(novelId:number,intent:PrivateGuideIntent):Promise<PrivateGuideJob>=> (await apiClient.post(path(novelId)+(intent.action==='create'?'/jobs':`/jobs/${intent.id}/${intent.action}`),intent.body)).data,
 artifact:async(novelId:number,id:number,signal?:AbortSignal):Promise<PrivateGuideArtifact>=>(await apiClient.get(path(novelId)+`/artifacts/${id}`,config(signal))).data,
 media:async(novelId:number,id:number,signal?:AbortSignal):Promise<Blob>=>(await apiClient.get(path(novelId)+`/artifacts/${id}/media`,{...config(signal),responseType:'blob'})).data,
};
const intentKey=(novelId:number)=>`private-guide-intent:${novelId}`;
export function loadPrivateGuideIntent(novelId:number):PrivateGuideIntent|null {try {const value=JSON.parse(accountStorage.getItem(intentKey(novelId))||'null');if(!value||!['create','cancel','retry'].includes(value.action)||typeof value.body?.operation_id!=='string'||!value.body.operation_id||value.body.operation_id.length>128)return null;if(value.action==='create'&&(!Number.isSafeInteger(value.body.provider_id)||typeof value.body.review_token!=='string'||!['guide','portrait'].includes(value.body.kind)))return null;if(value.action!=='create'&&(!Number.isSafeInteger(value.id)||!Number.isSafeInteger(value.body.expected_revision)))return null;return value;}catch{return null;}}
export function savePrivateGuideIntent(novelId:number,intent:PrivateGuideIntent|null){if(intent)accountStorage.setItem(intentKey(novelId),JSON.stringify(intent));else accountStorage.removeItem(intentKey(novelId));}

export function hasPendingPrivateGuideIntents():boolean {try {const prefix=accountStorageKey('private-guide-intent:');return Object.keys(localStorage).some(key=>key.startsWith(prefix)&&loadPrivateGuideIntent(Number(key.slice(prefix.length)))!==null);}catch{return false;}}
