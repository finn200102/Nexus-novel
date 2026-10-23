import {describe,expect,it} from "vitest";
import {alignedTo,audioLocator,audioTime,measuredManifest,planAudioPassages} from "./audioAlignment";
import type {ChapterDocument} from "../components/reader/chapterDocument";
const document:ChapterDocument={schema_version:1,source_format:"html",content_version:"source-a",plain_text:"😀 First passage. Another passage.",blocks:[{id:"first",kind:"p",html:"<p>😀 First passage.</p>",text:"😀 First passage."},{id:"note",kind:"p",html:"<p>A note.</p>",text:"A note.",role:"author_note"},{id:"last",kind:"p",html:"<p>Another passage.</p>",text:"Another passage."}]};
describe("measured audio passage links",()=>{
  it("preserves original UTF-16 offsets while normalizing spoken whitespace",()=>{
    const doc={...document,blocks:[{...document.blocks[0],text:"😀 alpha  beta\n\ngamma zzzzzzzzzzzzzzzzzzz"}]};
    const parts=planAudioPassages(doc,"Title",10);
    expect(parts[0].passage.block_id).toBeNull();
    for(const p of parts.slice(1)){expect(doc.blocks[0].text.slice(p.passage.text_offset!,p.passage.text_offset!+p.passage.text_length!).replace(/\s+/g," ")).toBe(p.text);}
    expect(parts.slice(1).map(p=>p.text.replace(/\s/g,"")).join("")).toBe(doc.blocks[0].text.replace(/\s/g,""));
    expect(planAudioPassages(document,"",100).map(p=>p.text)).toEqual(["😀 First passage.","Another passage."]);
  });
  it("links measured boundaries without interpolating word positions",()=>{
    const plan=planAudioPassages(document,"Title",100);const map=measuredManifest(document.content_version,plan.map(p=>p.passage),[1,4,2])!;
    expect(audioLocator(map,document,.5)).toBeUndefined();
    expect(audioLocator(map,document,4.9)?.blockId).toBe("first");expect(audioLocator(map,document,5)?.blockId).toBe("last");
    expect(audioTime(map,document,{blockId:"first",textOffset:8})).toBe(1);
    expect(audioTime(map,document,{blockId:"note",textOffset:0})).toBeUndefined();
    expect(map.duration_seconds).toBe(7);
  });
  it("refuses changed originals, translation views and corrupt manifests",()=>{
    const plan=planAudioPassages(document,"",100);const map=measuredManifest(document.content_version,plan.map(p=>p.passage),[1,1])!;
    expect(alignedTo(map,{...document,content_version:"source-b"})).toBe(false);
    expect(audioTime(map,document,{blockId:"first"},"translated")).toBeUndefined();
    expect(audioLocator({...map,segments:[{...map.segments[0],text_offset:99999}]},document,0)).toBeUndefined();
    expect(alignedTo({...map,segments:[{...map.segments[0],end_seconds:NaN}]},document)).toBe(false);
    expect(measuredManifest("x",plan.map(p=>p.passage),[1])).toBeNull();
  });
  it("requires finite positive duration and contiguous timing covering the complete recording",()=>{
    const plan=planAudioPassages(document,"",100);
    const map=measuredManifest(document.content_version,plan.map(p=>p.passage),[0.1,0.2])!;
    expect(alignedTo(map,document)).toBe(true);
    for(const duration_seconds of [null,NaN,Infinity,0,-1,0.4]){
      expect(alignedTo({...map,duration_seconds},document)).toBe(false);
      expect(audioLocator({...map,duration_seconds},document,0)).toBeUndefined();
    }
    expect(alignedTo({...map,segments:map.segments.map((s,i)=>i===0?{...s,start_seconds:0.01}:s)},document)).toBe(false);
    expect(alignedTo({...map,segments:map.segments.map((s,i)=>i===1?{...s,start_seconds:0.11}:s)},document)).toBe(false);
    expect(alignedTo({...map,segments:map.segments.map((s,i)=>i===1?{...s,start_seconds:0.09}:s)},document)).toBe(false);
  });
});

describe('stable chapter identity at text/audio handoff',()=>{
  const identity={chapter_key:'11111111-1111-4111-8111-111111111111',manifest_epoch:'22222222-2222-4222-8222-222222222222',manifest_revision:'1'};
  const source={schema_version:1 as const,source_format:'text' as const,content_version:'same-source',plain_text:'Same passage',blocks:[{id:'p1',kind:'p',html:'<p>Same passage</p>',text:'Same passage'}]};
  it('refuses another immutable chapter even when text hash and block identifiers are identical',()=>{
    const manifest=measuredManifest(source.content_version,[{block_id:'p1',text_offset:0,text_length:12}],[3],false,null,identity)!;
    const other={...identity,chapter_key:'33333333-3333-4333-8333-333333333333'};
    expect(alignedTo(manifest,source,'original',other)).toBe(false);
    expect(audioLocator(manifest,source,1,'original',other)).toBeUndefined();
    expect(audioTime(manifest,source,{blockId:'p1',textOffset:0},'original',other)).toBeUndefined();
    expect(alignedTo(manifest,source,'original',{...identity,manifest_revision:'2'})).toBe(true);
  });
});

it('normalizes nullable server recording identity without inventing a current chapter or losing original timing',async()=>{const {audioManifestFromWire}=await import('./audioAlignment');const value=audioManifestFromWire({job_id:7,current_source:false,chapter_key:null,manifest_epoch:null,manifest_revision:null,source_version:'original-v1',rendition:'original',precision:'segment',segments:[{part_index:0,start_seconds:0,end_seconds:2}]});expect(value.chapter_key).toBeUndefined();expect(value.source_version).toBe('original-v1');expect(value.segments).toEqual([{part_index:0,start_seconds:0,end_seconds:2,block_id:null,text_offset:null,text_length:null}]);});

it('seeks every covered source block to the measured merged chunk start and rejects foreign spans',()=>{
 const doc={...document,blocks:document.blocks.filter(b=>b.role!=='author_note')};
 const first=doc.blocks[0],second=doc.blocks[1];
 const spans=[{block_id:first.id,text_offset:0,text_length:first.text.length},{block_id:second.id,text_offset:0,text_length:second.text.length}];
 const map=measuredManifest(doc.content_version,[spans[0]],[5])!;
 map.segments[0].source_spans=spans;
 expect(audioTime(map,doc,{blockId:second.id,textOffset:4})).toBe(0);
 expect(audioLocator(map,doc,2)?.blockId).toBe(first.id);
 expect(alignedTo({...map,segments:[{...map.segments[0],block_id:'foreign'}]},doc)).toBe(false);
 expect(alignedTo({...map,segments:[{...map.segments[0],source_spans:[...spans,{block_id:'foreign',text_offset:0,text_length:1}]}]},doc)).toBe(false);
});
