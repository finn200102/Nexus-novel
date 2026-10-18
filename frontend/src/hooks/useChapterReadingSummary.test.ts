import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { useChapterReadingSummary } from "./useChapterReadingSummary";
import { chapterService, type ChapterReadingSummary } from "../services/chapterService";
import { activateAccountStorage } from "../services/accountStorage";
vi.mock("../services/chapterService", () => ({ chapterService:{getReadingSummary:vi.fn()} }));
const value=(novel_id=11,revision=1):ChapterReadingSummary=>({novel_id,reading_run_key:null,revision,total_chapters:2001,followed_total:2001,completed_chapters:1,followed_completed_chapters:1,completion_basis:"recorded_checkpoints",completed_reading:false,current:{chapter_id:9,chapter_number:0,ordinal:2,followed_ordinal:2,percent:40},next_unread_chapter_id:9,next_unread_chapter_number:0,categories:["story"],categories_truncated:false});
beforeEach(()=>{vi.clearAllMocks();localStorage.clear();activateAccountStorage(1);});
it("never converts a failed or missing summary into invented zero counts",async()=>{
 vi.mocked(chapterService.getReadingSummary).mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(value());const {result}=renderHook(()=>useChapterReadingSummary(11));await waitFor(()=>expect(result.current.error).toContain("Could not refresh"));expect(result.current.summary).toBeNull();await act(async()=>{await result.current.refresh();});expect(result.current.summary?.completed_chapters).toBe(1);
});
it("does not let an older GET replace a newer adopted checkpoint revision",async()=>{
 let resolve!:(data:ChapterReadingSummary)=>void;vi.mocked(chapterService.getReadingSummary).mockReturnValue(new Promise(done=>{resolve=done;}));const {result}=renderHook(()=>useChapterReadingSummary(11));act(()=>result.current.adopt(value(11,5)));await act(async()=>resolve(value(11,2)));expect(result.current.summary?.revision).toBe(5);
});
it("fences late previous-account and previous-story responses",async()=>{
 let resolve!:(data:ChapterReadingSummary)=>void;vi.mocked(chapterService.getReadingSummary).mockReturnValueOnce(new Promise(done=>{resolve=done;})).mockResolvedValue(value(22,3));const {result,rerender}=renderHook(({id})=>useChapterReadingSummary(id),{initialProps:{id:11}});act(()=>{activateAccountStorage(2);rerender({id:22});});await waitFor(()=>expect(result.current.summary?.novel_id).toBe(22));await act(async()=>resolve({...value(11),completed_chapters:2000}));expect(result.current.summary?.novel_id).toBe(22);expect(result.current.summary?.completed_chapters).toBe(1);
});
