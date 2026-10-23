import {fireEvent,screen,waitFor} from "@testing-library/react";
import {vi,it,expect} from "vitest";
import {renderWithToasts} from "../organization/testUtils";
import {fixtureChapterIdentity} from "../../../tests/fixtures/chapterIdentity";
import FinishChapter from "./FinishChapter";
import {readerToolsService} from "../../services/readerToolsService";
vi.mock("../../services/readerToolsService",()=>({readerToolsService:{confirmRead:vi.fn().mockResolvedValue({})}}));
it("confirms only after the explicit finish action and sends current version/run identity",async()=>{
 const identity=fixtureChapterIdentity(11,0);renderWithToasts(<FinishChapter novelId={11} chapterNumber={0} version="current" runKey="run" identity={identity}/>);
 expect(readerToolsService.confirmRead).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole("button",{name:"I have finished this chapter"}));
 await waitFor(()=>expect(readerToolsService.confirmRead).toHaveBeenCalledWith(11,0,"current","run",identity));
});
it("keeps unverified chapter text disabled",()=>{renderWithToasts(<FinishChapter novelId={11} chapterNumber={1} version={null} runKey={null}/>);expect(screen.getByRole("button",{name:"I have finished this chapter"})).toBeDisabled();});
