import {mkdir} from 'node:fs/promises';
import type {Page} from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import {test,expect} from './fixtures';
const key='22222222-2222-4222-8222-222222222222';
async function setup(page:Page,lostAck=false){
 let resolved=false,lost=false;const operations:unknown[]=[];
 const review=()=>({id:5,novel_id:11,revision:resolved?2:1,total:1,applied:resolved?1:0,offset:0,limit:20,items:[{reference:{ref:'original-zero',chapter_number:0,source_version:'a'.repeat(64)},applied:resolved,candidates:[{chapter_key:key,chapter_number:-2,title:'Preserved original with a long descriptive chapter name',source_version:'b'.repeat(64),archived:true,evidence:['same_title_only']}],candidates_truncated:false}],warnings:['Imported checkpoints are inferred history, never verified reading evidence.']});
 await page.route(/127\.0\.0\.1:8000|localhost:8000|\/api\//,async route=>{
  const request=route.request(),url=new URL(request.url()),path=url.pathname.replace(/^\/api(?=\/)/,'');
  const base='/me/import-reading-reviews';
  if(path===base)return route.fulfill({json:{items:[review()],total:1,offset:0,limit:10}});
  if(path===base+'/5')return route.fulfill({json:review()});
  if(path===base+'/5/preview'){expect(request.postDataJSON()).toMatchObject({expected_revision:1,mappings:[{ref:'original-zero',chapter_key:key,confirm_changed_content:true}],keep_existing_place:true});return route.fulfill({json:{review_id:5,review_token:'explicit-original-review',expires_at:'2030-01-01T00:00:00Z',manifest_epoch:'11111111-1111-4111-8111-111111111111',manifest_revision:'3',selected:1,warnings:['Original quotes and versions stay unchanged; obsolete block locators are cleared.']}});}
  if(path===base+'/5/apply'){operations.push(request.postDataJSON());resolved=true;if(lostAck&&!lost){lost=true;return route.abort('failed');}return route.fulfill({json:{id:5,revision:2,applied:1,remaining:0,progress:'kept_local'}});}
  return route.fallback();
 });
 await page.goto('/settings/data');await expect.poll(()=>page.evaluate(()=>JSON.parse(localStorage.getItem('nexus-signed-in')||'null')?.id)).toBe(7);
 await page.getByText('Imported reading places and annotations',{exact:true}).click();await page.getByRole('button',{name:'Open import review 5'}).click();
 return operations;
}
test('imported reading binding has an explicit reviewed boundary and recovers the same operation after reload',async({signedInPage:page})=>{
 const operations=await setup(page,true);
 await page.getByRole('button',{name:/Choose archived chapter -2:/}).click();await page.getByRole('checkbox',{name:'I reviewed changed or unknown text for original-zero'}).check();await page.getByRole('checkbox',{name:/Keep my existing reading place/}).check();
 await page.getByRole('button',{name:'Preview imported chapter bindings'}).click();await expect(page.getByText(/Original quotes and versions stay unchanged/)).toBeVisible();expect(operations).toHaveLength(0);
 await page.getByRole('button',{name:'Apply reviewed import bindings'}).click();await expect(page.getByRole('dialog',{name:'Apply these imported chapter bindings?'})).toBeVisible();expect(operations).toHaveLength(0);
 await page.getByRole('button',{name:'Confirm imported bindings'}).click();await expect(page.getByRole('button',{name:'Check pending import binding'})).toBeVisible();expect(operations).toHaveLength(1);
 await page.reload();await page.getByText('Imported reading places and annotations',{exact:true}).click();await page.getByRole('button',{name:'Check pending import binding'}).click();
 await expect(page.getByText(/Reviewed chapter bindings were confirmed/)).toBeVisible();expect(operations).toHaveLength(2);expect(operations[1]).toEqual(operations[0]);await expect(page.getByText('Chapter binding already reviewed.')).toBeVisible();
});
test('imported chapter choices preserve signed labels and fit an accessible phone review',async({signedInPage:page},info)=>{
 await setup(page);await mkdir('/tmp/nexus-portable-ui-review',{recursive:true});await page.screenshot({path:`/tmp/nexus-portable-ui-review/${info.project.name}-desktop.png`,fullPage:true});await page.setViewportSize({width:390,height:844});await page.addStyleTag({content:'*,*::before,*::after{animation:none!important;transition:none!important}'});
 await expect(page.getByRole('heading',{name:'Imported chapter · Original chapter 0'})).toBeVisible();await expect(page.getByRole('button',{name:/Choose archived chapter -2:/})).toBeVisible();
 await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth)).toBe(390);
 const result=await new AxeBuilder({page}).include('.import-reading-reviews').analyze();expect(result.violations).toEqual([]);await page.screenshot({path:`/tmp/nexus-portable-ui-review/${info.project.name}-phone.png`,fullPage:true});
});

test('URL-less private imports report unavailable originals and retained conflicts without source requests',async({signedInPage:page})=>{
 let submissions=0;
 await page.route(/127\.0\.0\.1:8000|localhost:8000|\/api\//,async route=>{
  const path=new URL(route.request().url()).pathname.replace(/^\/api(?=\/)/,'');
  if(path!=='/me/import')return route.fallback();
  submissions+=1;const document=route.request().postDataJSON();expect(document.libraries[0].novels[0].url).toBeNull();expect(document.libraries[0].novels[0].portable_story.story_epoch).toBe('11111111-1111-4111-8111-111111111111');
  const base={url:null,status:'created',reason:null,follow_state:null,progress:null,history:{added:0,updated:0,unchanged:0},annotations:{added:0,duplicate:0,deferred:0}};
  return route.fulfill({json:{format:'nexus-user-export',version:2,summary:{novels_created:1,novels_conflicts:1},saved_searches:[],libraries:[{name:'Private books',status:'created',novels:[{...base,title:'Private book without a source',novel_id:71,original_status:'unavailable'},{...base,status:'conflict',title:'Deleted private original',portable_link_id:3,reason:'The destination was deleted. Its imported material is retained for review.'}]}]}});
 });
 await page.goto('/settings/data');await expect.poll(()=>page.evaluate(()=>JSON.parse(localStorage.getItem('nexus-signed-in')||'null')?.id)).toBe(7);
 const exportDocument={format:'nexus-user-export',version:2,libraries:[{name:'Private books',novels:[{url:null,title:'Private book without a source',portable_story:{source_account_key:'22222222-2222-4222-8222-222222222222',story_epoch:'11111111-1111-4111-8111-111111111111'}}]}]};
 await page.getByLabel('Nexus data export file').setInputFiles({name:'private-books.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(exportDocument))});
 await expect(page.getByText(/Its original content is unavailable here/)).toBeVisible();await expect(page.getByText(/Deleted private original \(Private books\): The destination was deleted/)).toBeVisible();expect(submissions).toBe(1);
 await page.setViewportSize({width:390,height:844});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth)).toBe(390);
});
