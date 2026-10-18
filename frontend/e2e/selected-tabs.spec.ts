import {test,expect} from "./fixtures";
const novelId=100;
test("a phone reveals its directly linked reading-history tab without moving page or focus",async({signedInPage:page})=>{
  await page.setViewportSize({width:390,height:844});
  await page.route(/127\.0\.0\.1:8000|localhost:8000|\/api\//,async route=>{
    const path=new URL(route.request().url()).pathname.replace(/^\/api(?=\/)/,"");
    if(path===`/novel/${novelId}`)return route.fulfill({json:{id:novelId,library_id:1,title:"Selected tabs fixture",author:"Fixture",metadata_id:null,url:"nexus-local:tabs",novel_site:"local",chapter_count:1,num_chapters:1,scrape_status:"completed"}});
    if(path===`/chapter/${novelId}`)return route.fulfill({json:[{id:10003,novel_id:novelId,chapter_number:3,title:"First",content_status:"PRESENT"}]});
    if(path===`/reading/stories/${novelId}/runs`)return route.fulfill({json:{novel_id:novelId,current_run_key:null,current_progress:null,revision:0,first_chapter_number:3,total:0,offset:0,limit:20,items:[]}});
    if(path==="/reading/journal")return route.fulfill({json:{total:0,offset:0,limit:20,items:[]}});
    return route.fallback();
  });
  await page.goto(`/library/1/novels/${novelId}?tab=history`);
  const tabs=page.getByRole("tablist",{name:"Story sections",exact:true}),history=tabs.getByRole("tab",{name:"Reading history",exact:true});
  await expect(history).toHaveAttribute("aria-selected","true");
  const geometry=()=>tabs.evaluate(list=>{
    const container=list.parentElement!,selected=list.querySelector<HTMLElement>('[aria-selected="true"]')!;
    const viewport=container.getBoundingClientRect(),tab=selected.getBoundingClientRect();
    return{revealed:tab.left>=viewport.left-1 && tab.right<=viewport.right+1,left:container.scrollLeft,focus:document.activeElement?.getAttribute("role"),pageY:window.scrollY,pageWidth:document.documentElement.scrollWidth};
  });
  await expect.poll(async()=>(await geometry()).revealed).toBe(true);
  expect((await geometry()).left).toBeGreaterThan(0);expect((await geometry()).focus).not.toBe("tab");expect((await geometry()).pageWidth).toBe(390);
  // Stabilize only document height so panel-content height differences cannot
  // naturally clamp the viewport while checking that Tabs never scrolls it.
  await page.addStyleTag({content:"body { min-height: 3000px; }"});
  await page.evaluate(()=>window.scrollTo(0,300));
  await history.evaluate(element=>(element as HTMLButtonElement).focus({preventScroll:true}));
  const originalY=(await geometry()).pageY;
  await page.keyboard.press("Home");await expect(tabs.getByRole("tab",{name:"About",exact:true})).toBeFocused();
  await expect.poll(async()=>(await geometry()).revealed).toBe(true);expect((await geometry()).pageY).toBe(originalY);
  await page.emulateMedia({reducedMotion:"reduce"});
  await page.keyboard.press("End");await expect(tabs.getByRole("tab",{name:"Details",exact:true})).toBeFocused();
  await expect.poll(async()=>(await geometry()).revealed).toBe(true);expect((await geometry()).pageY).toBe(originalY);
  await page.keyboard.press("ArrowLeft");await page.keyboard.press("ArrowLeft");await expect(history).toBeFocused();
  await expect(history).toHaveAttribute("aria-selected","true");await expect.poll(async()=>(await geometry()).revealed).toBe(true);
  expect((await geometry()).pageY).toBe(originalY);
  await tabs.evaluate(list=>{list.parentElement!.style.maxWidth="260px";});
  await expect.poll(async()=>(await geometry()).revealed).toBe(true);expect((await geometry()).pageY).toBe(originalY);expect((await geometry()).pageWidth).toBe(390);
  await expect(history).toBeFocused();
});
