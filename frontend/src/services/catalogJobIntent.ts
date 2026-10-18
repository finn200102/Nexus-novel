import {accountStorage} from './accountStorage';
import type {CatalogQuery} from './catalogScrapeService';
import type {CreateCatalogRequest,UpdateCatalogRequest} from '../generated/api';
export type CatalogJobControl={expected_revision:string;operation_id:string};
export type BuiltinCatalogIntent={kind:'create';body:Omit<CreateCatalogRequest,'query'>&{query:CatalogQuery;review_token:string;operation_id:string};acknowledged_id?:number}|{kind:'update';id:number;body:Omit<UpdateCatalogRequest,'query'>&CatalogJobControl&{query?:CatalogQuery};acknowledged_id?:number}|{kind:'run'|'pause'|'resume'|'delete';id:number;body:CatalogJobControl;acknowledged_id?:number};
const key='catalog-builtin-operation';
export function loadCatalogJobIntent():BuiltinCatalogIntent|null{try{const value=JSON.parse(accountStorage.getItem(key)||'null');if(!value||!['create','update','run','pause','resume','delete'].includes(value.kind)||typeof value.body?.operation_id!=='string'||!value.body.operation_id||value.body.operation_id.length>128)return null;if(value.kind!=='create'&&(!Number.isSafeInteger(value.id)||value.id<1||typeof value.body.expected_revision!=='string'||!/^[a-f0-9]{64}$/.test(value.body.expected_revision)))return null;if(value.acknowledged_id!==undefined&&(!Number.isSafeInteger(value.acknowledged_id)||value.acknowledged_id<1))return null;return value;}catch{return null;}}
export function saveCatalogJobIntent(value:BuiltinCatalogIntent|null){if(value)accountStorage.setItem(key,JSON.stringify(value));else accountStorage.removeItem(key);}
