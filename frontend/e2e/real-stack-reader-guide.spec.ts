import {readFileSync} from "node:fs";
import {expect,test} from "@playwright/test";

test("reader guide verifies signed chapter evidence before sharing analysis or exposing identities and media",async({page,request})=>{
  test.skip(process.env.NEXUS_E2E_MODE!=="real" || !process.env.NEXUS_E2E_READER_GUIDE_FIXTURE,"Requires the disposable three-service guide fixture.");
  test.setTimeout(90_000);
  const fixture=JSON.parse(readFileSync(process.env.NEXUS_E2E_READER_GUIDE_FIXTURE!,"utf8"));
  await page.goto("/login");
  await page.getByLabel("Username").fill(process.env.NEXUS_E2E_USER!);
  await page.getByLabel("Password").fill(process.env.NEXUS_E2E_PASSWORD!);
  const login=page.waitForResponse(response=>response.url().endsWith("/api/auth/login") && response.request().method()==="POST");
  await page.getByRole("button",{name:"Sign in",exact:true}).click();
  const headers={Authorization:`Bearer ${(await(await login).json()).access_token}`};
  await expect(page).not.toHaveURL(/\/login/);
  const base=`/api/discovery/novels/${fixture.metadata_id}/story-guide`;
  const get=async(path:string)=>{const response=await request.get(path,{headers});expect(response.ok(),await response.text()).toBeTruthy();return response.json();};
  const safe=(value:unknown)=>{const text=JSON.stringify(value).toLowerCase();for(const secret of ["future_queen_name","future_portrait","secret_future_crown","secret queen","conquers everything"])expect(text).not.toContain(secret);};
  // Story pages request summaries, chapter pages and guides concurrently. A
  // synchronous account-lock wait on the event loop used to stall all of them.
  for(let attempt=0;attempt<3;attempt++){
    const responses=await Promise.all([
      `/api/chapter/reading-summary/${fixture.novel_id}`,
      `/api/chapter/reading-chapters/${fixture.novel_id}?offset=0&limit=100`,
      `${base}/projection?through_chapter=0`,
      "/api/library/",
    ].map(path=>request.get(path,{headers,timeout:15_000})));
    for(const response of responses)expect(response.ok(),await response.text()).toBeTruthy();
    expect((await responses[0].json()).total_chapters).toBe(3);
    expect((await responses[1].json()).items).toHaveLength(3);
    const scoped=await responses[2].json();expect(scoped.safe_through_chapter).toBe(-3);safe(scoped);
  }
  const projection=await get(`${base}/projection?through_chapter=0`);
  expect(projection.safe_through_chapter).toBe(-3);
  expect(projection.characters.map((row:{name:string})=>row.name)).toEqual(["Molly"]);
  expect(projection.characters[0].last_chapter).toBe(-3);
  expect(projection.reader_context).toEqual({library_id:fixture.library_id,novel_id:fixture.novel_id});
  expect(projection.assertions.map((row:{chapter:number})=>row.chapter)).toEqual([-3]);safe(projection);
  const guide=await get(`${base}?through_chapter=0`);
  expect(guide.through_chapter).toBe(-3);expect(guide.chapters_analyzed).toBe(1);
  expect(guide.characters[0].portrait).toBeNull();safe(guide);
  const identity=projection.characters[0].id;
  for(const suffix of ["/entities?through_chapter=0","/relationships?through_chapter=0","/changes?from_chapter=-4&through_chapter=0",
    `/entities/${identity}/profile?through_chapter=0`,"/relationships/timeline?through_chapter=0",`/entities/${identity}?through_chapter=0`,"/chapters/-3?through_chapter=0"]){
    safe(await get(`${base}${suffix}`));
  }
  const unread=await get(`${base}/projection?through_chapter=-4`);
  expect(unread.safe_through_chapter).toBeNull();expect(unread.characters).toEqual([]);expect(unread.assertions).toEqual([]);
  const unknown=await get(`/api/discovery/novels/${fixture.metadata_id+2}/story-guide/projection?through_chapter=0`);
  expect(unknown.safe_through_chapter).toBeNull();expect(unknown.characters).toEqual([]);safe(unknown);
  const futureDossier=await request.get(`${base}/chapters/0?through_chapter=0`,{headers});
  expect(futureDossier.status()).toBe(200);
  const withheld=await futureDossier.json();
  expect(withheld).toMatchObject({chapter:0,status:"not_yet_read",dossier:null,assertions:[],through_chapter:null});safe(withheld);
  const media=await request.get(`/api/discovery/story-guide/media/guide-acceptance-unprovenanced?novel_id=${fixture.metadata_id}`,{headers});
  expect(media.status()).toBe(404);expect(await media.text()).not.toContain("Future queen in crown");
  const replay=await request.post(`${base}/backfill`,{headers});
  expect(replay.ok(),await replay.text()).toBeTruthy();expect((await replay.json()).queued).toBe(0);
  expect(fixture.changed_metadata_id).toBe(fixture.metadata_id+1);
  const changed=await request.get(`/api/discovery/novels/${fixture.changed_metadata_id}/story-guide/projection`,{headers});
  expect(changed.status()).toBe(409);
  const rejection=await changed.json();
  expect(rejection.detail).toBe("Verified Story Guide evidence is unavailable or changed; review current chapter text before trying again");
  expect(JSON.stringify(rejection)).not.toContain("CHANGED shared original");safe(rejection);
  const original=await get(`/api/chapter/content/library/${fixture.library_id}/${fixture.novel_id}/-3`);
  expect(original.document.plain_text).toBe("Molly waits in the harbour.");
  for(const [suffix,data] of [["/regenerate",{}],["/characters/portrait",{name:"Molly"}]] as const){
    const denied=await request.post(`${base}${suffix}`,{headers,data});
    expect(denied.status()).toBe(403);expect((await denied.json()).detail.code).toBe("reader_provider_required");
  }
  const providers=await get("/api/reader/providers");
  const provider=providers.find((row:{name:string})=>row.name==="Fixture companion");expect(provider).toBeTruthy();
  const question="Where does Molly wait?";
  const answer=await request.post(`/api/reader/companion/${fixture.novel_id}/questions`,{headers,data:{provider_id:provider.id,question,through_chapter:0}});
  expect(answer.ok(),await answer.text()).toBeTruthy();
  const result=await answer.json();expect(result.through_chapter).toBe(-3);expect(result.citations.map((row:{chapter:number})=>row.chapter)).toEqual([-3]);safe(result);
  const recorded=await request.get(`http://127.0.0.1:${process.env.NEXUS_FIXTURE_SOURCE_PORT || "8090"}/ai/requests`);
  expect(recorded.ok()).toBeTruthy();
  const inputs=(await recorded.json()).requests.filter((row:{question?:string})=>row.question===question);
  expect(inputs).toHaveLength(1);expect(inputs[0].through_chapter).toBe(-3);
  expect(inputs[0].evidence.every((row:{chapter:number})=>row.chapter===-3)).toBeTruthy();safe(inputs);
});
