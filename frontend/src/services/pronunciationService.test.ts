import {describe,expect,it} from "vitest";
import {applyPronunciation,normalizePronunciationRules,planPronouncedPassages} from "./pronunciationService";
import {planAudioPassages} from "./audioAlignment";
import type {ChapterDocument} from "../components/reader/chapterDocument";
const rules=[{source:"Ann",spoken:"An"},{source:"Anna",spoken:"AH nah"},{source:".*",spoken:"dot star"},{source:"AH",spoken:"changed"}];
const document:ChapterDocument={schema_version:1,source_format:"html",content_version:"source",plain_text:"😀 Anna meets Ann. .* Ann",blocks:[{id:"one",kind:"p",html:"<p>😀 <em>Anna</em> meets Ann. .* Ann</p>",text:"😀 Anna meets Ann. .* Ann"},{id:"note",kind:"p",html:"<p>Anna note</p>",text:"Anna note",role:"author_note"}]};
describe("literal pronunciation copies",()=>{
  it("matches literals longest first, respects case and never cascades replacement output",()=>{
    expect(applyPronunciation("Anna Ann anna .* AH",rules)).toBe("AH nah An anna dot star changed");
    expect(applyPronunciation("a+b [x] $1",[{source:"a+b",spoken:"plus"},{source:"[x]",spoken:"ex"},{source:"$1",spoken:"dollar"}])).toBe("plus ex dollar");
  });
  it("preserves original UTF16 spans and rich source while bounding expanded spoken parts",()=>{
    const before=JSON.stringify(document),parts=planPronouncedPassages(document,"Anna",12,false,rules);
    expect(parts[0]).toMatchObject({text:"AH nah",passage:{block_id:null}});
    for(const part of parts.slice(1)){
      expect(part.text.length).toBeLessThanOrEqual(12);
      const original=document.blocks[0].text.slice(part.passage.text_offset!,part.passage.text_offset!+part.passage.text_length!);
      expect(applyPronunciation(original,rules).replace(/\s+/g," ")).toBe(part.text);
    }
    expect(parts.slice(1).map(part=>part.text).join("")).not.toContain("note");expect(JSON.stringify(document)).toBe(before);
    expect(planPronouncedPassages(document,"",100,true,rules).some(part=>part.passage.block_id==="note")).toBe(true);
  });
  it("uses legacy planning unchanged when no overrides exist",()=>{
    expect(planPronouncedPassages(document,"Title",10)).toEqual(planAudioPassages(document,"Title",10));
  });
  it("rejects duplicate, unsafe, empty or unbounded rules",()=>{
    for(const source of [""," ","<speak>","x\u202ey","x\ny","x".repeat(81)])expect(()=>normalizePronunciationRules([{source,spoken:"say"}])).toThrow();
    expect(()=>normalizePronunciationRules([{source:"x",spoken:"say"},{source:"x",spoken:"other"}])).toThrow(/once/);
    expect(()=>normalizePronunciationRules([{source:"x",spoken:"x".repeat(161)}])).toThrow();
    expect(()=>planPronouncedPassages(document,"Anna",3,false,rules)).toThrow(/longer/);
  });
});

describe("chapter narration budgets",()=>{
  const makeDocument=(text:string):ChapterDocument=>({...document,plain_text:text,blocks:[{id:"source",kind:"p",html:`<p>${text}</p>`,text}]});
  it("accepts the exact spoken budget and rejects expansion before materializing oversized output",()=>{
    const original=makeDocument("x".repeat(12500)),before=JSON.stringify(original),override=[{source:"x",spoken:"y".repeat(160)}];
    const result=planPronouncedPassages(original,"",20000,false,override);
    expect(result.reduce((sum,part)=>sum+part.text.length,0)).toBe(2_000_000);
    expect(()=>planPronouncedPassages(original,"x",20000,false,override)).toThrow(/2,000,000 spoken characters or 10,000 parts/);
    expect(JSON.stringify(original)).toBe(before);
  });
  it("accepts 10000 parts, rejects the next, and preserves a legacy 162-part chapter",()=>{
    const many={...document,blocks:Array.from({length:10000},(_,index)=>({id:String(index),kind:"p" as const,html:"<p>a</p>",text:"a"}))};
    expect(planPronouncedPassages(many,"",100)).toHaveLength(10000);
    expect(()=>planPronouncedPassages(many,"title",100)).toThrow(/Shorten or disable/);
    expect(()=>planPronouncedPassages(many,"title",100,false,[{source:"a",spoken:"b"}])).toThrow(/Shorten or disable/);
    expect(planPronouncedPassages(makeDocument("a".repeat(1620)),"",10)).toHaveLength(162);
  });
});
