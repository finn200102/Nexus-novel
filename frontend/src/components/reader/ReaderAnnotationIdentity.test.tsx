import {render,screen,within} from '@testing-library/react';
import {expect,it,vi} from 'vitest';
import {AnnotationsSheet,type ReadingAnnotation} from './ReaderPanels';
const key='11111111-1111-4111-8111-111111111111';
it('does not group a different immutable chapter at the current numeric address or invent a jump for unresolved notes',()=>{
 const rows:ReadingAnnotation[]=[{id:1,annotation_type:'note',chapter_number:0,chapter_key:key,position:0,percent:40,note:'Original prologue note'}, {id:2,annotation_type:'note',position:0,percent:50,note:'Unresolved retained note',identity_unresolved:true,original_chapter_number:7}];
 render(<AnnotationsSheet open onClose={vi.fn()} annotations={rows} chapterNumber={0} chapterKey='22222222-2222-4222-8222-222222222222' onJump={vi.fn()} onDelete={vi.fn()}/>);
 expect(screen.queryByRole('heading',{name:'This chapter'})).toBeNull();expect(screen.getByRole('heading',{name:'Other chapters'})).toBeInTheDocument();
 const unresolved=screen.getByRole('button',{name:/^Note: Unresolved retained note/});expect(unresolved).toBeDisabled();expect(within(unresolved).getByText(/Original chapter needs identity review/)).toBeInTheDocument();expect(screen.queryByText('Chapter undefined')).toBeNull();
});

it('edits only current chapter notes and preserves the quoted source',async()=>{
 const {fireEvent,waitFor}=await import('@testing-library/react');
 const current:ReadingAnnotation={id:1,annotation_type:'highlight',chapter_number:1,chapter_key:key,position:2,percent:40,note:'Before',quote:'Immutable source'};
 const other:ReadingAnnotation={...current,id:2,chapter_number:2,chapter_key:'22222222-2222-4222-8222-222222222222',note:'Elsewhere'};
 const onEdit=vi.fn().mockResolvedValue(undefined),onJump=vi.fn();
 const {rerender}=render(<AnnotationsSheet open onClose={vi.fn()} annotations={[current,other]} chapterNumber={1} chapterKey={key} onJump={onJump} onDelete={vi.fn()} onEdit={onEdit}/>);
 expect(screen.getAllByRole('button',{name:'Edit note'})).toHaveLength(1);
 fireEvent.click(screen.getByRole('button',{name:'Open chapter to edit'}));expect(onJump).toHaveBeenCalledWith(other);
 fireEvent.click(screen.getByRole('button',{name:'Edit note'}));
 fireEvent.change(screen.getByRole('textbox',{name:'Note'}),{target:{value:'After'}});
 fireEvent.click(screen.getByRole('button',{name:'Save note'}));
 await waitFor(()=>expect(onEdit).toHaveBeenCalledWith(current,'After'));
 expect(current.quote).toBe('Immutable source');
 fireEvent.click(screen.getByRole('button',{name:'Edit note'}));
 rerender(<AnnotationsSheet open={false} onClose={vi.fn()} annotations={[current]} chapterNumber={1} chapterKey={key} onJump={onJump} onDelete={vi.fn()} onEdit={onEdit}/>);
 expect(screen.queryByRole('dialog',{name:'Edit note'})).toBeNull();
});
