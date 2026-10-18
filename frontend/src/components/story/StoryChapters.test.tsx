import {fixtureChapterIdentity as identity} from "../../../tests/fixtures/chapterIdentity";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import StoryChapters from "./StoryChapters";
import { renderWithToasts } from "../organization/testUtils";
import { chapterManifestService } from "../../services/chapterManifestService";
import { chapterService, type ChapterReadingItem, type ChapterReadingSummary } from "../../services/chapterService";
import { activateAccountStorage } from "../../services/accountStorage";
import type { OfflineCopies } from "../novel/useOfflineCopies";
vi.mock("../../services/chapterService", () => ({chapterService:{getReadingChapters:vi.fn(),getReadingSummary:vi.fn(),getDownloadStatus:vi.fn(),resetChapterStatus:vi.fn(),downloadChapter:vi.fn(),deleteChaptersByIds:vi.fn()}}));
vi.mock("../../services/organizationService",()=>({organizationService:{getPersonal:vi.fn().mockResolvedValue({followed_categories:["story"]}),savePersonal:vi.fn().mockResolvedValue({})}}));
vi.mock("../../services/chapterManifestService",async original=>({...await original<typeof import("../../services/chapterManifestService")>(),chapterManifestService:{state:vi.fn(),history:vi.fn()}}));
vi.mock("../../services/downloadService",()=>({downloadService:{queue:vi.fn()}}));
vi.mock("../novel/AutoDownloadToggle",()=>({default:()=>null}));
vi.mock("../novel/OfflineControl",()=>({default:()=>null}));
const summary=():ChapterReadingSummary=>({novel_id:11,reading_run_key:null,revision:2,total_chapters:2001,followed_total:2000,completed_chapters:1,followed_completed_chapters:1,completion_basis:"recorded_checkpoints",completed_reading:false,current:{chapter_id:3,chapter_number:20007,ordinal:3,followed_ordinal:3,percent:40},next_unread_chapter_id:1,next_unread_chapter_number:-2,categories:["story","appendix"],categories_truncated:false});
const item=(index:number):ChapterReadingItem=>({...identity(11,index===0?-2:index===1?0:index+20005),id:index+1,novel_id:11,chapter_number:index===0?-2:index===1?0:index+20005,title:`Part ${index}`,category:"story",content_status:"PRESENT",audio_status:"MISSING",created_at:"2026-10-16T00:00:00Z",updated_at:"2026-10-16T00:00:00Z",ordinal:index+1,followed_ordinal:index+1,followed:true,completed_checkpoint:index===1,max_percent:index===1?100:index===2?40:null});
const offline:OfflineCopies={stored:[],totalBytes:0,progress:null,message:null,busy:false,review:null,saveBatch:vi.fn(),reviewBatch:vi.fn(),confirmBatch:vi.fn(),cancelBatch:vi.fn(),removeAll:vi.fn()};
const onSummary=vi.fn();
const mount=()=>renderWithToasts(<MemoryRouter><StoryChapters libraryId={1} novelId={11} onReadingSummary={onSummary} offline={offline} followSettings={null} onFollowSettings={vi.fn()}/></MemoryRouter>);
beforeEach(()=>{
 vi.clearAllMocks();vi.mocked(chapterManifestService.state).mockResolvedValue({novel_id:11,...identity(11,-2),identity_required:false,total:2001,items:[],next_cursor:null,has_more:false});vi.mocked(chapterManifestService.history).mockResolvedValue({items:[],total:0,offset:0,limit:10,has_more:false});localStorage.clear();activateAccountStorage(1);vi.mocked(chapterService.getReadingSummary).mockResolvedValue(summary());vi.mocked(chapterService.getDownloadStatus).mockResolvedValue({total:2001,present:1999,missing:2,failed:0,processing:0,processing_chapters:[],failed_chapters:[]});
 vi.mocked(chapterService.getReadingChapters).mockImplementation(async(_id,params={})=>({novel_id:11,reading_run_key:null,revision:2,total:params.q?1:params.category_scope==="all"?2001:2000,offset:params.offset??0,limit:100,items:params.q?[item(0)]:Array.from({length:100},(_,index)=>item((params.offset??0)+index))}));
});
it("shows the actual place and count independently, marking only recorded completed chapters",async()=>{
 mount();await screen.findByText("Current place: Chapter 20007 · 3 of 2001 in story · 40%");expect(screen.getByText("1 of 2001 completed chapters recorded · 1999 downloaded on the server · 0 saved offline")).toBeInTheDocument();
 expect(screen.getAllByRole("img",{name:"Completed chapter recorded"})).toHaveLength(1);
 const zero=screen.getByRole("link",{name:"Chapter 0: Part 1"}).closest("li")!;expect(within(zero).getByRole("img",{name:"Completed chapter recorded"})).toBeInTheDocument();
 const negative=screen.getByRole("link",{name:"Chapter -2: Part 0"}).closest("li")!;expect(within(negative).getByRole("img",{name:"No completed chapter record"})).toBeInTheDocument();
 const current=screen.getByRole("link",{name:"Chapter 20007: Part 2"}).closest("li")!;expect(within(current).getByText(/Current place · 40% recorded/)).toBeInTheDocument();expect(within(current).getByRole("img",{name:"No completed chapter record"})).toBeInTheDocument();
});
it("uses true server totals beyond1000 and bounded pages, with literal search across the full story",async()=>{
 mount();await screen.findByRole("link",{name:"Chapter -2: Part 0"});expect(screen.getByText("1–100 of 2000 matching chapters")).toBeInTheDocument();
 fireEvent.click(screen.getByRole("button",{name:"Next chapters"}));await screen.findByRole("link",{name:"Chapter 20105: Part 100"});expect(chapterService.getReadingChapters).toHaveBeenLastCalledWith(11,{offset:100,limit:100,q:"",category_scope:"followed"});expect(screen.getByText("101–200 of 2000 matching chapters")).toBeInTheDocument();
 fireEvent.change(screen.getByRole("searchbox",{name:"Find chapter"}),{target:{value:"-2"}});await screen.findByRole("link",{name:"Chapter -2: Part 0"});expect(chapterService.getReadingChapters).toHaveBeenLastCalledWith(11,{offset:0,limit:100,q:"-2",category_scope:"all"});expect(screen.getByText("1–1 of 1 matching chapters")).toBeInTheDocument();
});
it("does not fill chapter records when a reading was explicitly marked finished",async()=>{
 vi.mocked(chapterService.getReadingSummary).mockResolvedValue({...summary(),completed_reading:true,completed_chapters:0,followed_completed_chapters:0});vi.mocked(chapterService.getReadingChapters).mockResolvedValue({novel_id:11,reading_run_key:null,revision:2,total:1,offset:0,limit:100,items:[{...item(2),completed_checkpoint:false,max_percent:40}]});mount();await screen.findByText("This reading is marked finished. Chapter records are shown separately.");expect(screen.getByText(/0 of 2001 completed chapters recorded/)).toBeInTheDocument();expect(screen.queryByRole("img",{name:"Completed chapter recorded"})).not.toBeInTheDocument();
});
it("rejects mixed reading-run snapshots instead of showing incorrect markers",async()=>{
 vi.mocked(chapterService.getReadingChapters).mockResolvedValue({novel_id:11,reading_run_key:"old-run",revision:1,total:1,offset:0,limit:100,items:[{...item(0),completed_checkpoint:true}]});mount();await screen.findByText(/reading session changed while loading/);expect(screen.queryByRole("img",{name:"Completed chapter recorded"})).not.toBeInTheDocument();
});
it("fences delayed chapter pages after an account change",async()=>{
 let resolve!:(value:Awaited<ReturnType<typeof chapterService.getReadingChapters>>)=>void;vi.mocked(chapterService.getReadingChapters).mockReturnValueOnce(new Promise(done=>{resolve=done;})).mockResolvedValue({novel_id:11,reading_run_key:null,revision:2,total:0,offset:0,limit:100,items:[]});mount();await waitFor(()=>expect(chapterService.getReadingChapters).toHaveBeenCalledOnce());await act(async()=>{activateAccountStorage(2);resolve({novel_id:11,reading_run_key:null,revision:2,total:1,offset:0,limit:100,items:[{...item(0),title:"Previous account private chapter"}]});});expect(screen.queryByText("Previous account private chapter")).not.toBeInTheDocument();
});

it("replaces bulk deletion with the explicit source review without removing chapters or downloads",async()=>{
 const view=mount();await screen.findByRole("link",{name:"Chapter -2: Part 0"});expect(chapterManifestService.state).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole("button",{name:"Select chapters"}));fireEvent.click(screen.getByRole("checkbox",{name:"Chapter -2: Part 0"}));
 expect(screen.getByRole("button",{name:"Download 1 selected"})).toBeEnabled();expect(screen.queryByRole("button",{name:/Delete selected/})).toBeNull();
 fireEvent.click(screen.getByRole("button",{name:/^Review chapter changes$/}));await screen.findByRole("region",{name:"Reviewed chapter list changes"});
 expect(view.container.querySelector(".chapter-changes-disclosure")).toHaveAttribute("open");expect(screen.getByText("Review chapter list changes",{exact:true})).toHaveFocus();
 expect(chapterService.deleteChaptersByIds).not.toHaveBeenCalled();expect(chapterService.downloadChapter).not.toHaveBeenCalled();expect(screen.queryByText(/downloaded text is removed from the server/)).toBeNull();expect(screen.getByRole("button",{name:"Select chapters"})).toBeInTheDocument();
});
