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
