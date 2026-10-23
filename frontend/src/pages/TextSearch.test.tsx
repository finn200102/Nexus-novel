import {act,render,screen} from "@testing-library/react";
import {MemoryRouter} from "react-router-dom";
import {it,expect,vi,beforeEach} from "vitest";
import TextSearch from "./TextSearch";
import apiClient from "../services/apiClient";
import {activateAccountStorage} from "../services/accountStorage";
vi.mock("../services/apiClient",()=>({default:{get:vi.fn()},getUserFacingError:()=>"Search failed"}));
beforeEach(()=>{vi.clearAllMocks();activateAccountStorage(1);});
it("links scoped text matches by owned library and exact chapter identity, clearing private snippets on account switch",async()=>{
 vi.mocked(apiClient.get).mockResolvedValueOnce({data:{total:1,matches:[{novel_id:2,library_id:4,novel_title:"Book",chapter_id:7,chapter_number:0,chapter_title:"Opening",chapter_key:"key",snippet:"PRIVATE MATCH"}]}});
 render(<MemoryRouter initialEntries={["/search?q=the&novel_id=2"]}><TextSearch/></MemoryRouter>);
 await screen.findByText("PRIVATE MATCH");
 expect(screen.getByRole("link",{name:"Book · Chapter 0: Opening"})).toHaveAttribute("href","/library/4/novels/2/0?chapter_key=key");
 vi.mocked(apiClient.get).mockImplementation(()=>new Promise(()=>{}));
 act(()=>activateAccountStorage(2));
 expect(screen.queryByText("PRIVATE MATCH")).not.toBeInTheDocument();
});
it("does not send an unbounded one-letter search",()=>{render(<MemoryRouter initialEntries={["/search?q=a"]}><TextSearch/></MemoryRouter>);expect(apiClient.get).not.toHaveBeenCalled();expect(screen.getByRole("button",{name:"Search"})).toBeDisabled();});
