import { createHash } from "node:crypto";
import { test, expect } from "./fixtures";

const novelId=96,providerId=31,revisionProviderId=32;
const html="<p>Before <em>😀 selected</em> after.</p>";
const text="Before 😀 selected after.";
const version=createHash("sha256").update(html).digest("hex");
const document={schema_version:1,source_format:"html",content_version:version,plain_text:text,blocks:[{id:"passage-original",kind:"p",html,text}]};

test("original nested Unicode selection survives reader menus and requires explicit remote consent",async({signedInPage:page})=>{
  const requests:Record<string,unknown>[]=[],revisions:Record<string,unknown>[]=[];
  await page.route(/127\.0\.0\.1:8000|localhost:8000|\/api\//,async route=>{
    const path=new URL(route.request().url()).pathname.replace(/^\/api(?=\/)/,"");
    if(path===`/novel/${novelId}`)return route.fulfill({json:{id:novelId,library_id:1,title:"Selected passage fixture",author:"Fixture",metadata_id:null,url:"nexus-local:passage",novel_site:"ao3",chapter_count:1,num_chapters:1,scrape_status:"completed"}});
    if(path===`/chapter/${novelId}`)return route.fulfill({json:[{id:9601,novel_id:novelId,chapter_number:1,title:"Original",content_status:"PRESENT"}]});
    if(path===`/chapter/content/library/1/${novelId}/1`)return route.fulfill({json:{id:9601,novel_id:novelId,chapter_number:1,title:"Original",content_status:"PRESENT",content:text,document}});
    if(path===`/chapter/annotations/${novelId}`)return route.fulfill({json:[]});
    if(path===`/chapter/progress/${novelId}`)return route.fulfill({json:null});
    if(path==="/reader/providers")return route.fulfill({json:[{id:providerId,name:"Explicit remote fixture",kind:"openai_compatible",model:"fixture-model",enabled:true,budget_usd:10,used_usd:0,reserved_usd:0},{id:revisionProviderId,name:"Explicit premium fixture",kind:"anthropic",model:"premium-fixture",enabled:true,budget_usd:10,used_usd:0,reserved_usd:0}]});
    if(path===`/reader/permissions/${novelId}/${providerId}` || path===`/reader/permissions/${novelId}/${revisionProviderId}`)return route.fulfill({json:{translation:null,companion:null,is_ao3:true,ao3_consent:false,local:false}});
    if(path===`/reader/translations/${novelId}/1`)return route.fulfill({json:[]});
    if(path===`/reader/translations/${novelId}/1/passage-revision`){
      const value=route.request().postDataJSON();revisions.push(value);
      return route.fulfill({json:{original:value.quote,draft:value.draft,translation:"<em>literal premium revision</em>",anchor:{content_version:version,block_id:"passage-original",text_offset:5,text_length:13,quote:text.slice(5,18)},provider_id:revisionProviderId,language:"de",mode:"revision",input_tokens:10,output_tokens:5,charged_usd:.00003}});
    }
    if(path===`/reader/translations/${novelId}/1/passage-preview`){
      const value=route.request().postDataJSON();requests.push(value);
      return route.fulfill({json:{original:value.quote,translation:"<script>literal translation</script>",anchor:{content_version:version,block_id:"passage-original",text_offset:5,text_length:13,quote:text.slice(5,18)},provider_id:providerId,language:"de",input_tokens:10,output_tokens:5,charged_usd:.00002}});
    }
    return route.fallback();
  });
  await page.goto(`/library/1/novels/${novelId}/1`);
  const content=page.locator(".reader__content"),block=page.locator('[data-block-id="passage-original"]');
  await expect(content).toHaveAttribute("aria-busy","false");
  await expect(block).toHaveText(text);
  const before=await block.innerHTML();
  // Select actual rendered text across a formatting boundary, including a
  // complete supplementary Unicode character. Engines retain native ranges.
  await block.evaluate(async element=>{
    const paragraph=element.querySelector("p")!,emphasis=paragraph.querySelector("em")!;
    const range=window.document.createRange();range.setStart(paragraph.firstChild!,5);range.setEnd(emphasis.firstChild!,11);
    const selection=window.getSelection()!;selection.removeAllRanges();selection.addRange(range);
    await new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve())));
  });
  await expect.poll(()=>page.evaluate(()=>window.getSelection()?.toString())).toBe(text.slice(5,18));
  await page.getByRole("button",{name:"More reader actions",exact:true}).click();
  await page.getByRole("menuitem",{name:"Translation & story companion",exact:true}).click();
  const dialog=page.getByRole("dialog",{name:"Translation & story companion",exact:true});
  await expect(dialog.getByRole("heading",{name:"Translate selected passage",exact:true})).toBeVisible();
  await expect(dialog.locator("blockquote")).toHaveText(text.slice(5,18));
  await dialog.getByRole("combobox",{name:"Provider",exact:true}).selectOption(String(providerId));
  const translate=dialog.getByRole("button",{name:"Translate this passage",exact:true});
  await expect(translate).toBeDisabled();expect(requests).toEqual([]);
  await dialog.getByRole("switch",{name:"Allow sending this AO3 material and read evidence to this external provider",exact:true}).click();
  await expect(translate).toBeEnabled();expect(requests).toEqual([]);
  await translate.click();
  await expect(dialog.locator("p").filter({hasText:/^<script>literal translation<\/script>$/})).toBeVisible();
  expect(requests).toEqual([{provider_id:providerId,language:"de",content_version:version,block_id:"passage-original",text_offset:5,text_length:13,quote:text.slice(5,18),external_consent:true,ao3_consent:true}]);
  expect(await block.innerHTML()).toBe(before);await expect(block).toHaveText(text);
  await expect(dialog.locator("script")).toHaveCount(0);
  expect(revisions).toEqual([]);
  await dialog.getByText("Revise this draft with a chosen provider",{exact:true}).click();
  const revise=dialog.getByRole("button",{name:"Revise reviewed draft",exact:true});
  await expect(revise).toBeDisabled();expect(revisions).toEqual([]);
  await dialog.getByRole("combobox",{name:"Revision provider",exact:true}).selectOption(String(revisionProviderId));
  await expect(revise).toBeDisabled();
  await dialog.getByLabel("Passage draft to revise",{exact:true}).fill("A reviewed and edited economy draft.");
  const allowRevision=dialog.getByRole("switch",{name:"Allow sending this AO3 passage and draft to the revision provider",exact:true});
  await expect(allowRevision).toBeEnabled();expect(revisions).toEqual([]);
  await allowRevision.click();await expect(revise).toBeEnabled();expect(revisions).toEqual([]);
  await revise.click();
  await expect(dialog.getByText("<em>literal premium revision</em>",{exact:true})).toBeVisible();
  expect(revisions).toEqual([{provider_id:revisionProviderId,language:"de",content_version:version,block_id:"passage-original",text_offset:5,text_length:13,quote:text.slice(5,18),draft:"A reviewed and edited economy draft.",external_consent:true,ao3_consent:true}]);
  expect(requests).toHaveLength(1);
  await expect(dialog.locator("em")).toHaveCount(0);
  expect(await block.innerHTML()).toBe(before);await expect(block).toHaveText(text);

});
