import {fireEvent,render,screen} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {describe,it,expect,vi} from 'vitest';
import StoryAbout from './StoryAbout';
import {toStoryView} from './storyModel';

function mount(throughChapter:number|null) {
  const prepare=vi.fn();
  render(<MemoryRouter><StoryAbout view={{...toStoryView(null,null),metadataId:4}} inLibrary signals={[]} analysisState="not_started" enriching={false} onEnrich={vi.fn()} similar={[]} guide={{chapters_analyzed:0,through_chapter:throughChapter,characters:[],chapters:[]}} guideCutoff={undefined} buildingGuide={false} onBuildGuide={prepare} onHide={vi.fn()} progress={null} onSaveNext={vi.fn()} savingOffline={false} offlineCount={0}/></MemoryRouter>);
  return prepare;
}

describe('story evidence preparation boundary',()=>{
  it('explains explicit reading confirmation and blocks an unknown verified boundary',()=>{
    const prepare=mount(null);
    const button=screen.getByRole('button',{name:'Prepare local chapter evidence'});
    expect(button).toBeDisabled();
    expect(screen.getByText(/I have finished this downloaded chapter/)).toHaveTextContent(/Translation & story companion/);
    fireEvent.click(button);
    expect(prepare).not.toHaveBeenCalled();
  });
  it.each([0,-2])('accepts an explicitly verified boundary at chapter %s',chapter=>{
    const prepare=mount(chapter);
    const button=screen.getByRole('button',{name:'Prepare local chapter evidence'});
    expect(button).toBeEnabled();
    fireEvent.click(button);
    expect(prepare).toHaveBeenCalledOnce();
    expect(screen.queryByText(/I have finished this downloaded chapter/)).toBeNull();
  });
});
