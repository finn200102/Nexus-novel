import { fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import ChapterDrawer from './ChapterDrawer';
import { organizationService } from '../../services/organizationService';
import { offlineReaderStore } from '../../services/offlineReaderStore';
vi.mock('../../services/organizationService',()=>({organizationService:{getPersonal:vi.fn()}}));
vi.mock('../../services/offlineReaderStore',()=>({offlineReaderStore:{listForNovel:vi.fn()}}));
beforeEach(()=>{
 vi.mocked(organizationService.getPersonal).mockResolvedValue({followed_categories:['story']} as never);
 vi.mocked(offlineReaderStore.listForNovel).mockResolvedValue([]);
});
it('keeps the current locator separate from recorded completion and never infers read status from chapter numbers',async()=>{
 const onSelect=vi.fn();render(<ChapterDrawer open onClose={vi.fn()} novelId={42} currentChapter={0} lastReadChapter={100} onSelect={onSelect} chapters={[
  {chapter_number:-2,title:'Unknown old prologue'},
  {chapter_number:0,title:'Current place'},
  {chapter_number:7,title:'Recorded earlier',completed_checkpoint:true},
  {chapter_number:11,title:'No checkpoint',completed_checkpoint:false},
  {chapter_number:200,title:'Unknown future chapter'},
 ]}/>);
 const current=await screen.findByRole('button',{name:/Chapter 0 Current place/});expect(current).toHaveAttribute('aria-current','true');
 expect(screen.getAllByText('No completed checkpoint')).toHaveLength(1);
 expect(within(screen.getByRole('button',{name:/Chapter 11 No checkpoint/})).getByText('No completed checkpoint')).toBeInTheDocument();
 for(const name of [/Chapter -2 Unknown old prologue/,/Chapter 7 Recorded earlier/,/Chapter 200 Unknown future chapter/])expect(within(screen.getByRole('button',{name})).queryByText('No completed checkpoint')).toBeNull();
 expect(screen.queryByText(/^Unread$/)).toBeNull();fireEvent.click(current);expect(onSelect).toHaveBeenCalledWith(0);
});
