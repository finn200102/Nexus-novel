import { render,screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe,expect,it } from "vitest";
import LibraryStoryCard from "./LibraryStoryCard";
describe("library reading place labels",()=>{
 it.each([-2,0,20007])("keeps source chapter%s separate from actual chapter count",chapter=>{
  render(<MemoryRouter><LibraryStoryCard novel={{id:7,library_id:2,title:"Private book",url:null,chapter_count:3,next_unread_chapter_number:chapter}} libraryId={2} selectionMode={false} selected={false} onToggleSelect={()=>undefined} shelves={[]}/></MemoryRouter>);
  const link=screen.getByRole("link",{name:`Continue Private book at chapter ${chapter}`});expect(link).toHaveAttribute("href",`/library/2/novels/7/${chapter}`);expect(link).toHaveTextContent(`Next: Chapter ${chapter} · 3 chapters`);expect(link).not.toHaveTextContent(" of ");expect(screen.getByRole("link",{name:"Private book"})).toHaveAttribute("href","/library/2/novels/7");
 });
});
