import {render,screen} from "@testing-library/react";
import {MemoryRouter} from "react-router-dom";
import {it,expect,vi} from "vitest";
import ProblemsTab from "./ProblemsTab";
vi.mock("../../context/AuthContext",()=>({useAuth:()=>({user:{is_admin:false}})}));
vi.mock("../../services/novelService",()=>({novelService:{getAllNovels:vi.fn().mockResolvedValue([])}}));
it("preserves saved-content guidance and requests admin source review without bypassing authority",()=>{
 render(<MemoryRouter><ProblemsTab libraryId={1} jobs={[{id:1,novel_id:2,status:"failed",error_code:"source_review_required"} as never]} setJobs={vi.fn()} sources={[]}/></MemoryRouter>);
 expect(screen.getByText(/Your saved chapter text is preserved/)).toHaveTextContent("Ask your administrator");
 expect(screen.getByRole("link",{name:"Review this story’s chapter changes"})).toHaveAttribute("href","/library/1/novels/2?tab=chapters");
 expect(screen.queryByRole("link",{name:"Review source lifecycle"})).not.toBeInTheDocument();
});
