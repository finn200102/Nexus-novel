import {act,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {beforeEach,describe,expect,it,vi} from 'vitest';
import TextRevisionPanel from './TextRevisionPanel';
import {textRevisionService} from '../../services/textRevisionService';
import {activateAccountStorage} from '../../services/accountStorage';
vi.mock('../../services/textRevisionService',()=>({textRevisionService:{style:vi.fn(),saveStyle:vi.fn(),preview:vi.fn()}}));
const props={novelId:1,chapter:2,provider:{id:3,name:'Local',kind:'local',model:'qwen',base_url:'http://local/v1',budget_usd:0,used_usd:0,reserved_usd:0},identity:{chapter_key:'chapter',manifest_epoch:'epoch',manifest_revision:'1'},sourceVersion:'source',variants:[]};
beforeEach(()=>{vi.clearAllMocks();activateAccountStorage(1);vi.mocked(textRevisionService.style).mockResolvedValue({revision:0,style_guide:''});vi.mocked(textRevisionService.saveStyle).mockResolvedValue({revision:1,style_guide:'Preserve names'});vi.mocked(textRevisionService.preview).mockResolvedValue({original:'Bad grammar',draft:'Bad grammar',preview:'<script>reviewed prose</script>',mode:'proofreading',saved:false,source_version:'source'});});
describe('reviewable text tools',()=>{
  it('requires explicit request and shows literal before/after without applying',async()=>{
    render(<TextRevisionPanel {...props}/>);
    await waitFor(()=>expect(screen.getByRole('button',{name:'Generate editing preview'})).toBeEnabled());
    expect(textRevisionService.preview).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button',{name:'Generate editing preview'}));
    expect(await screen.findByText('<script>reviewed prose</script>')).toBeInTheDocument();
    expect(screen.getByText('Bad grammar')).toBeVisible();
    expect(document.querySelector('script')).toBeNull();
    expect(screen.queryByRole('button',{name:/apply/i})).toBeNull();
    fireEvent.click(screen.getByRole('button',{name:'Discard preview'}));
    expect(screen.queryByText('<script>reviewed prose</script>')).toBeNull();
  });
  it('requires saving style and sends exact selection on explicit rewrite',async()=>{
    const passage={content_version:'source',block_id:'b',text_offset:0,text_length:4,quote:'Text'};
    render(<TextRevisionPanel {...props} passage={passage}/>);
    await waitFor(()=>expect(screen.getByRole('button',{name:'Save story style guide'})).toBeEnabled());
    fireEvent.change(screen.getByLabelText('Story style guide'),{target:{value:'Preserve names'}});
    expect(screen.getByRole('button',{name:'Generate editing preview'})).toBeDisabled();
    fireEvent.click(screen.getByRole('button',{name:'Save story style guide'}));
    expect(await screen.findByText('Story style guide saved.')).toBeVisible();
    fireEvent.change(screen.getByLabelText('Editing operation'),{target:{value:'rewrite'}});
    fireEvent.change(screen.getByLabelText('Editing scope'),{target:{value:'passage'}});
    fireEvent.click(screen.getByRole('button',{name:'Generate editing preview'}));
    await waitFor(()=>expect(textRevisionService.preview).toHaveBeenCalledWith(1,2,3,'rewrite',props.identity,'source',passage,undefined));
  });
  it('blocks remote providers and drops results after unmount',async()=>{
    const view=render(<TextRevisionPanel {...props} provider={{...props.provider,kind:'openai_compatible'}}/>);
    await screen.findByText(/Choose a local conversational model/);
    expect(screen.getByRole('button',{name:'Generate editing preview'})).toBeDisabled();
    view.unmount();
    let done!:(value:never)=>void;
    vi.mocked(textRevisionService.preview).mockImplementation(()=>new Promise(resolve=>{done=resolve;}));
    const local=render(<TextRevisionPanel {...props}/>);
    await waitFor(()=>expect(screen.getByRole('button',{name:'Generate editing preview'})).toBeEnabled());
    fireEvent.click(screen.getByRole('button',{name:'Generate editing preview'}));
    local.unmount();
    await act(async()=>done({preview:'PRIVATE OLD RESPONSE'} as never));
    expect(screen.queryByText('PRIVATE OLD RESPONSE')).toBeNull();
  });
});
