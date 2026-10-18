import {mkdir} from 'node:fs/promises';
import AxeBuilder from '@axe-core/playwright';
import {test,expect} from './fixtures';
const key='11111111-1111-4111-8111-111111111111',capture='22222222-2222-4222-8222-222222222222';
test('source lifecycle decisions are explicit, reviewed and recoverable',async({signedInPage:page},info)=>{
 let applied=false,undone=false,previewCount=0,applyCount=0;const submitted:unknown[]=[];
 const source={site:'fanfiction',story_id:5,source_url:'https://example.org/story'};
 const cap={id:capture,fingerprint:'b'.repeat(64),total:1,source_complete:true,deletion_authoritative:false,authority_kind:'raw_observation'};
 const original={chapter_key:key,chapter_number:-2,title:'A very long preserved original title with meaningful words and no false numeric identity',url:null,archived:false,has_cached_content:true};
 const context={novel_id:5,title:'Source fixture',manifest_key:key,revision:'a'.repeat(64),source,capture:cap,originals:[original],observations:[{capture_ordinal:0,chapter_number:0,title:original.title,url:null,category:'chapter',candidates:[{chapter_key:key,evidence:'unique_meaningful_title'}],decision:null,new_chapter_key:null}],original_total:1,observation_total:1,offset:0,limit:50};
 const review=()=>({...context,observations:context.observations.map(row=>({...row,decision:{capture_ordinal:0,chapter_key:key,new_lifecycle:false}})),id:capture,original_novel_id:5,revision:applied?2:1,status:undone?'undone':applied?'applied':'preview',ready:true,review_token:'review-token',expires_at:'2026-10-18',created_at:'2026-10-16',applied_at:applied?'2026-10-16':null,undone_at:null,manifest_revision:context.revision,facts_fingerprint:'c'.repeat(64),counts:{mapped_continuations:1,new_lifecycles:0,archived_originals:1,unresolved_originals:0,unresolved_observations:0},warnings:['Original bodies remain archived.'],can_undo:applied&&!undone,undo_blocked_reason:null,applied_capture_id:null});
 await page.route(/127\.0\.0\.1:8000|localhost:8000|\/api\//,async route=>{const path=new URL(route.request().url()).pathname.replace(/^\/api(?=\/)/,'');
 if(path==='/admin/review-catalog/lookup')return route.fulfill({json:{items:[{novel_id:5,story_key:key,title:'Source fixture',site:'fanfiction',author:null,source_url:source.source_url}],total:1,offset:0,limit:10,has_more:false}});
 if(path==='/admin/source-manifest-reviews/novels/5/head')return route.fulfill({json:{protocol:1,novel_id:5,manifest_key:key,revision:context.revision,source,capture:{...cap,captured_at:'2026-10-16',review_id:null}}});
 if(path==='/admin/source-manifest-reviews/novels/5/context')return route.fulfill({json:context});
 if(path==='/admin/source-manifest-reviews/preview'){previewCount++;submitted.push(route.request().postDataJSON());return route.fulfill({json:review()});}
 if(path===`/admin/source-manifest-reviews/${capture}/apply`){applyCount++;submitted.push(route.request().postDataJSON());applied=true;return route.fulfill({json:{review:review(),replayed:false}});}
 if(path===`/admin/source-manifest-reviews/${capture}/undo`){undone=true;return route.fulfill({json:{review:review(),replayed:false}});}
 if(path===`/admin/source-manifest-reviews/${capture}`)return route.fulfill({json:review()});
 if(path==='/admin/source-manifest-reviews')return route.fulfill({json:{items:[],total:0,offset:0,limit:20}});
 return route.fallback();});
 await page.goto('/admin/duplicates');await page.getByText('Reviewed source chapter lifecycles',{exact:true}).click();
 const region=page.getByRole('region',{name:'Source chapter lifecycle review'});
 await region.getByRole('button',{name:'Search source story',exact:true}).click();await region.getByRole('button',{name:'Choose source story: Source fixture · fanfiction'}).click();
 await expect(region.getByLabel('Decision for observed slot 1')).toHaveValue('');expect(previewCount).toBe(0);expect(applyCount).toBe(0);
 await region.getByRole('button',{name:'Confirm unique title suggestions on this page'}).click();
 await region.getByRole('button',{name:'Preview source lifecycle decisions'}).click();await expect(region.getByRole('button',{name:'Review and apply source lifecycles'})).toBeEnabled();
 expect(submitted[0]).toMatchObject({novel_id:5,capture_id:capture,expected_manifest_key:key,expected_revision:'a'.repeat(64),mappings:[{capture_ordinal:0,chapter_key:key,new_lifecycle:false}],archive_keys:[]});
 await page.setViewportSize({width:390,height:844});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
 const scan=await new AxeBuilder({page}).include('section[aria-label="Source chapter lifecycle review"]').analyze();expect(scan.violations).toEqual([]);
 await mkdir('/tmp/nexus-source-lifecycle-native',{recursive:true});await page.screenshot({path:`/tmp/nexus-source-lifecycle-native/${info.project.name}-phone.png`,fullPage:true});
 await region.getByRole('button',{name:'Review and apply source lifecycles'}).click();expect(applyCount).toBe(0);await page.getByRole('button',{name:'Confirm source lifecycle changes'}).click();await expect(region.getByText('Action confirmed. Current status: applied.')).toBeVisible();expect(applyCount).toBe(1);expect(submitted[1]).toMatchObject({expected_revision:1,review_token:'review-token'});expect(submitted[1]).not.toHaveProperty('actor_id');await region.getByRole('button',{name:'Review source lifecycle undo'}).click();await page.getByRole('button',{name:'Confirm source lifecycle undo'}).click();await expect(region.getByText('Action confirmed. Current status: undone.')).toBeVisible();
});
