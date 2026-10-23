import { render,screen,fireEvent } from "@testing-library/react";
import { MemoryRouter,useLocation } from "react-router-dom";
import { describe,expect,it } from "vitest";
import LibraryStoryCard from "./LibraryStoryCard";
describe("library reading place labels",()=>{
 it.each([-2,0,20007])("keeps source chapter%s separate from actual chapter count",chapter=>{
  render(<MemoryRouter><LibraryStoryCard novel={{id:7,library_id:2,title:"Private book",url:null,chapter_count:3,next_unread_chapter_number:chapter}} libraryId={2} selectionMode={false} selected={false} onToggleSelect={()=>undefined} shelves={[]}/></MemoryRouter>);
  const link=screen.getByRole("link",{name:`Continue Private book at chapter ${chapter}`});expect(link).toHaveAttribute("href",`/library/2/novels/7/${chapter}`);expect(link).toHaveTextContent(`Next: Chapter ${chapter} · 3 chapters`);expect(link).not.toHaveTextContent(" of ");expect(screen.getByRole("link",{name:"Private book"})).toHaveAttribute("href","/library/2/novels/7");
 });
});

function ReturnState(){const location=useLocation();return <output>{(location.state as {libraryReturn?:string}|null)?.libraryReturn}</output>;}
it("carries the full filtered library return URL when opening a story",()=>{
 render(<MemoryRouter initialEntries={["/library?q=harbour&sort=title&offset=50"]}><LibraryStoryCard novel={{id:7,library_id:2,title:"Return book",url:null}} libraryId={2} selectionMode={false} selected={false} onToggleSelect={()=>undefined} shelves={[]}/><ReturnState/></MemoryRouter>);
 fireEvent.click(screen.getByRole("link",{name:"Return book"}));
 expect(screen.getByText("/library?q=harbour&sort=title&offset=50")).toBeInTheDocument();
});
