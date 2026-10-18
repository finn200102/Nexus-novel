import {beforeEach,expect,it,vi} from "vitest";
import apiClient from "./apiClient";
import {liveSearchService,normalizeLiveResult} from "./liveSearchService";
vi.mock("./apiClient",()=>({default:{get:vi.fn()}}));
beforeEach(()=>vi.resetAllMocks());
it("normalizes sparse plugin metadata while preserving source identity and null catalog ID",()=>{expect(normalizeLiveResult({id:null,metadata_id:null,title:"Serial",source_url:"https://fixture.invalid/serial",source_id:"plugin-example",sources:["live"]})).toMatchObject({id:null,metadata_id:null,title:"Serial",source_url:"https://fixture.invalid/serial",author:null,description:null,img_url:null,word_count:null,chapter_count:null,status:null,sources:["live"]});});
it("pins a reviewed source digest and forwards cancellation without paid fallback",async()=>{const signal=new AbortController().signal;vi.mocked(apiClient.get).mockResolvedValue({data:{source_id:"plugin-example",page:2,has_more:null,results:[],errors:[]}});await liveSearchService.source("moon","plugin-example",2,signal,"a".repeat(64));expect(apiClient.get).toHaveBeenCalledWith("/discovery/live/source",{params:{q:"moon",source_id:"plugin-example",page:2,pinned_digest:"a".repeat(64)},signal,timeout:60000});});
it("retains the legacy aggregate method and repeated query format",async()=>{vi.mocked(apiClient.get).mockResolvedValue({data:{page:1,results:[],errors:[]}});await liveSearchService.search("moon & stars",["archive","royalroad"]);expect(apiClient.get).toHaveBeenCalledWith("/discovery/live?q=moon+%26+stars&sites=archive&sites=royalroad&page=1",{timeout:60000});});
