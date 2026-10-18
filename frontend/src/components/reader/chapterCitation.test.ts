import {expect,it} from 'vitest';
import {chapterCitationHref} from './chapterCitation';
const key='11111111-1111-4111-8111-111111111111';
it('routes verified signed chapter citations with immutable identity and keeps unknown legacy references unlinked',()=>{
 expect(chapterCitationHref('/reader',{chapter:0,block_id:'a & b',chapter_key:key})).toBe(`/reader/0?block=a%20%26%20b&chapter_key=${key}`);
 expect(chapterCitationHref('/reader',{chapter:-2,block_id:'p',chapter_key:key})).toContain('/-2?');
 expect(chapterCitationHref('/reader',{chapter:7,block_id:'p'})).toBeNull();
 expect(chapterCitationHref('/reader',{chapter:7,block_id:'p',chapter_key:'provider-invented-key'})).toBeNull();
});
