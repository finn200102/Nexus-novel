import axios from "axios";
import { afterEach, expect, it, vi } from "vitest";
import { discoveryService } from "./discoveryService";
import { novelService } from "./novelService";
import { libraryService } from "./libraryService";
import { chapterService } from "./chapterService";

afterEach(()=>vi.restoreAllMocks());
it.each([discoveryService,novelService,libraryService,chapterService])("diagnostics exclude credentials, private bodies and source query strings",service=>{
  const log=vi.spyOn(console,"error").mockImplementation(()=>undefined);
  const error={isAxiosError:true,code:"ERR_BAD_RESPONSE",response:{status:503,data:{secret:"private chapter"}},
    config:{headers:{Authorization:"Bearer private-token"},url:"/private?key=private-key"}};
  service.handleError(error,"Discovery request failed");
  expect(log).toHaveBeenCalledWith("Discovery request failed",{status:503,code:"ERR_BAD_RESPONSE"});
  expect(JSON.stringify(log.mock.calls)).not.toMatch(/private|Bearer|Authorization/);
  log.mockClear();service.handleError(new axios.CanceledError(),"cancelled");expect(log).not.toHaveBeenCalled();
});
