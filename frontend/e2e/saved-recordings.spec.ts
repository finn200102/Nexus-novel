import {mkdir} from 'node:fs/promises';
import AxeBuilder from '@axe-core/playwright';
import {test,expect} from './fixtures';
test('preserved recordings stay playable without claiming a current chapter',async({signedInPage:page},info)=>{
  const novelId=11;let requests=0;
  await page.route(/127\.0\.0\.1:8000|localhost:8000|\/api\//,async route=>{
    const path=new URL(route.request().url()).pathname.replace(/^\/api(?=\/)/,'');
    if(path===`/audio/stories/${novelId}`)return route.fulfill({json:{novel_id:novelId,total:0,offset:0,limit:50,
      summary:{chapters:0,downloaded:0,ready:0,queued:0,needs_retry:0},chapters:[]}});
    if(path===`/audio/stories/${novelId}/recordings`)return route.fulfill({json:{items:[{id:71,status:'completed',provider_id:'custom',provider_voice:'Saved narrator',provider_model:'local',
      total_parts:2,completed_parts:2,audio_ready:true,source_identity_current:false,source_identity_inferred:true,
      chapter_key:null,chapter_number:null,chapter_title_snapshot:null,chapter_number_snapshot:null}],total:1,offset:0,limit:50}});
    if(path===`/audio/jobs/71/audio`){requests++;const body=Buffer.alloc(44+48000);body.write('RIFF');body.writeUInt32LE(body.length-8,4);
      body.write('WAVEfmt ',8);body.writeUInt32LE(16,16);body.writeUInt16LE(1,20);body.writeUInt16LE(1,22);body.writeUInt32LE(24000,24);
      body.writeUInt32LE(48000,28);body.writeUInt16LE(2,32);body.writeUInt16LE(16,34);body.write('data',36);body.writeUInt32LE(body.length-44,40);
      return route.fulfill({contentType:'audio/wav',body});}
    if(path===`/audio/pronunciation/stories/${novelId}`)return route.fulfill({json:{scope:`pronunciation:${novelId}`,revision:0,rules:[],account_rules:[],inherit_account:true,effective_rules:[],effective_version:'none'}});
    if(path==='/audio/voices/default')return route.fulfill({json:{voice_profile_id:null,revision:0}});
    if(path==='/audio/voices')return route.fulfill({json:[]});
    return route.fallback();
  });
  await page.goto(`/library/1/novels/${novelId}?tab=audio`);
  await page.getByText('Saved recordings and preserved originals',{exact:true}).click();
  const region=page.getByRole('region',{name:'Saved recordings',exact:true});
  await expect(region.getByRole('heading',{name:'Saved recording 71',exact:true})).toBeVisible();
  await expect(region.getByText(/link to a current chapter cannot be verified/)).toBeVisible();
  await expect(region.getByRole('link')).toHaveCount(0);
  await region.getByRole('button',{name:'Listen to saved recording 71',exact:true}).click();
  await expect(page.getByLabel('Listen to Saved recording 71',{exact:true})).toHaveAttribute('src',/^blob:/);
  expect(requests).toBe(1);
  await page.setViewportSize({width:390,height:844});
  await expect(region.getByRole('button',{name:'Download saved recording 71'})).toBeVisible();
  const geometry=await page.evaluate(()=>({width:window.innerWidth,scroll:document.documentElement.scrollWidth,overflow:[...document.querySelectorAll('body *')].map(element=>({element:element.tagName,className:element.className,rect:element.getBoundingClientRect(),text:element.textContent?.slice(0,90)})).filter(item=>item.rect.right>window.innerWidth+1||item.rect.left< -1).map(item=>({...item,rect:{left:item.rect.left,right:item.rect.right,width:item.rect.width}}))}));
  expect(geometry.scroll,JSON.stringify(geometry)).toBeLessThanOrEqual(geometry.width);
  const scan=await new AxeBuilder({page}).include('section[aria-label="Saved recordings"]').analyze();
  expect(scan.violations.filter(item=>['serious','critical'].includes(item.impact||''))).toEqual([]);
  await mkdir('/tmp/nexus-manifest-saved-recordings-native',{recursive:true});
  await page.screenshot({path:`/tmp/nexus-manifest-saved-recordings-native/${info.project.name}-phone.png`,fullPage:true});
  await page.evaluate(()=>{(window as Window&{savedRecordingPlayer?:HTMLAudioElement}).savedRecordingPlayer=document.querySelector('audio[aria-label="Listen to Saved recording 71"]') as HTMLAudioElement;});
  await page.getByRole('tab',{name:'About',exact:true}).click();
  await expect(page.getByRole('tab',{name:'About',exact:true})).toHaveAttribute('aria-selected','true');
  await expect.poll(()=>page.evaluate(()=>{const player=(window as Window&{savedRecordingPlayer?:HTMLAudioElement}).savedRecordingPlayer;
    return {paused:player?.paused,source:player?.getAttribute('src')};})).toEqual({paused:true,source:null});
});
