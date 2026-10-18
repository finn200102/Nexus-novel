import { mkdir, writeFile } from "node:fs/promises";
import AxeBuilder from "@axe-core/playwright";
import { test, expect } from "./fixtures";
import type { SavedSearch, SavedSearchDefinition } from "../src/services/savedSearchService";

test("saved discovery query keeps its source, similarity and filters through review, reopen and delete",async({signedInPage:page},info)=>{
  let rows:SavedSearch[]=[];
  const writes:Array<{name:string;definition:SavedSearchDefinition;expected_revision?:string}>=[];
  await page.route(/\/saved-searches(?:\/\d+)?(?:\?|$)/,async route=>{
    const request=route.request();
    if(request.method()==="GET")return route.fulfill({json:rows});
    if(request.method()==="DELETE"){expect(new URL(request.url()).searchParams.get("expected_revision")).toBe(rows[0].revision);rows=[];return route.fulfill({json:{deleted:true}});}
    const payload=request.postDataJSON();writes.push(payload);
    rows=[{id:4,name:payload.name,definition:payload.definition,filters:payload.definition.filters,notify_on_match:false,revision:String(writes.length).repeat(64),needs_review:false,warnings:[],alert_state:"off",created_at:"2026-10-16T00:00:00Z",updated_at:"2026-10-16T00:00:00Z"}];
    return route.fulfill({json:rows[0],status:request.method()==="POST"?201:200});
  });
  const filters={tag:["Adventure"],crossover:"true",sortBy:"favorites",sortOrder:"desc"};
  await page.goto(`/discover/fanfiction?${new URLSearchParams({q:"dragon & moon",similar_to:"912",filters:JSON.stringify(filters)})}`);
  await page.getByRole("button",{name:"Save current search",exact:true}).click();
  const dialog=page.getByRole("dialog",{name:"Save search",exact:true});
  await expect(dialog.getByLabel("Text query",{exact:true})).toHaveValue("dragon & moon");
  await expect(dialog.getByLabel("Source",{exact:true})).toHaveValue("fanfiction");
  await dialog.getByRole("textbox",{name:/Search name/}).fill("Evening adventure");
  await dialog.getByRole("button",{name:"Save reviewed search",exact:true}).click();
  await expect(page.getByRole("button",{name:"Open Evening adventure",exact:true})).toBeVisible();
  expect(writes[0].definition).toMatchObject({q:"dragon & moon",site:"fanfiction",similar_to:912,filters});
  await page.getByRole("button",{name:"Open Evening adventure",exact:true}).click();
  await expect(page).toHaveURL(url=>url.pathname==="/discover/fanfiction" && url.searchParams.get("q")==="dragon & moon" && url.searchParams.get("similar_to")==="912");
  await page.getByRole("button",{name:"Edit Evening adventure",exact:true}).click();
  const edit=page.getByRole("dialog",{name:"Review saved search",exact:true});
  await edit.getByLabel("Text query",{exact:true}).fill("new moon");
  await edit.getByLabel("Source",{exact:true}).selectOption("royalroad");
  await page.setViewportSize({width:390,height:844});
  await mkdir("/tmp/nexus-saved-searches-ui",{recursive:true});
  await page.screenshot({path:`/tmp/nexus-saved-searches-ui/${info.project.name}-phone-edit.png`,animations:"disabled"});
  const axe=await new AxeBuilder({page}).include('[role="dialog"]').analyze();
  await writeFile(`/tmp/nexus-saved-searches-ui/${info.project.name}-phone-axe.json`,JSON.stringify(axe.violations,null,2));
  expect(axe.violations).toEqual([]);
  const bounds=await edit.boundingBox();expect(bounds!.x).toBeGreaterThanOrEqual(0);expect(bounds!.x+bounds!.width).toBeLessThanOrEqual(391);
  await edit.getByRole("button",{name:"Save reviewed search",exact:true}).click();
  expect(writes[1].expected_revision).toBe("1".repeat(64));expect(writes[1].definition).toMatchObject({q:"new moon",site:"royalroad",similar_to:912,filters});
  await page.getByRole("button",{name:"Open Evening adventure",exact:true}).click();
  await expect(page).toHaveURL(url=>url.pathname==="/discover/royalroad" && url.searchParams.get("q")==="new moon");
  await page.getByRole("button",{name:"Delete Evening adventure",exact:true}).click();
  await page.getByRole("dialog").getByRole("button",{name:"Delete saved search",exact:true}).click();
  await expect(page.getByText("No saved searches yet.",{exact:true})).toBeVisible();
});
