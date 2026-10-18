import {act,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {beforeEach,describe,expect,it,vi} from 'vitest';
import StorySavedRecordings from './StorySavedRecordings';
import {audioService} from '../../services/audioService';
import {activateAccountStorage} from '../../services/accountStorage';
vi.mock('../../services/audioService',()=>({audioService:{recordings:vi.fn(),audio:vi.fn(),cancel:vi.fn()}}));
const recording={id:12,status:'completed',provider_id:'custom',provider_voice:'Saved narrator',provider_model:'local',
  total_parts:2,completed_parts:2,attempt_count:1,max_attempts:3,created_at:'2026-01-01T00:00:00',updated_at:'2026-01-01T00:00:00',
  audio_ready:true,source_identity_current:false,source_identity_inferred:true,chapter_key:null,chapter_number:null,
  chapter_title_snapshot:null,chapter_number_snapshot:null};
const page={items:[recording],total:1,offset:0,limit:50};
describe('private saved recordings',()=>{
  beforeEach(()=>{vi.clearAllMocks();activateAccountStorage(null);vi.mocked(audioService.recordings).mockResolvedValue(page);
    vi.spyOn(HTMLMediaElement.prototype,'pause').mockImplementation(()=>{});
    vi.spyOn(HTMLMediaElement.prototype,'load').mockImplementation(()=>{});
    vi.mocked(audioService.audio).mockResolvedValue(new Blob(['RIFFfixture'],{type:'audio/wav'}));
    URL.createObjectURL=vi.fn(()=> 'blob:private-recording');URL.revokeObjectURL=vi.fn();});
  it('plays an unbound original without linking it to a current chapter',async()=>{
    const {unmount}=render(<StorySavedRecordings novelId={9}/>);
    expect(await screen.findByRole('heading',{name:'Saved recording 12'})).toBeVisible();
    expect(screen.getByText(/link to a current chapter cannot be verified/)).toBeVisible();
    expect(screen.queryByRole('link')).toBeNull();
    fireEvent.click(screen.getByRole('button',{name:'Listen to saved recording 12'}));
    await waitFor(()=>expect(screen.getByLabelText('Listen to Saved recording 12')).toHaveAttribute('src','blob:private-recording'));
    expect(audioService.audio).toHaveBeenCalledWith(12);
    unmount();expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:private-recording');
    expect(HTMLMediaElement.prototype.pause).toHaveBeenCalled();
  });
  it('discards a late private blob after changing accounts',async()=>{
    activateAccountStorage(801);let finish!:(value:Blob)=>void;
    vi.mocked(audioService.audio).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
    render(<StorySavedRecordings novelId={9}/>);
    fireEvent.click(await screen.findByRole('button',{name:'Listen to saved recording 12'}));
    act(()=>activateAccountStorage(802));
    await act(async()=>finish(new Blob(['PRIVATE OLD ACCOUNT'])));
    expect(URL.createObjectURL).not.toHaveBeenCalled();
    expect(screen.queryByLabelText('Listen to Saved recording 12')).toBeNull();
    act(()=>activateAccountStorage(null));
  });
  it('pages actual saved jobs and offers retry after a failed read',async()=>{
    vi.mocked(audioService.recordings).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({...page,total:51});
    render(<StorySavedRecordings novelId={9}/>);
    fireEvent.click(await screen.findByRole('button',{name:'Retry saved recordings'}));
    await screen.findByRole('heading',{name:'Saved recording 12'});
    fireEvent.click(screen.getByRole('button',{name:'Next recordings'}));
    await waitFor(()=>expect(audioService.recordings).toHaveBeenLastCalledWith(9,50));
  });
});
