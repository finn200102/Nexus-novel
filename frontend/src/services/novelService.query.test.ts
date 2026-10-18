import {expect,it,vi} from "vitest";
import apiClient from "./apiClient";
import {novelService} from "./novelService";

it("keeps literal query characters from changing the legacy library scope",async()=>{
  const get=vi.spyOn(apiClient,"get").mockResolvedValue({data:[]});
  try{
    await novelService.getAllNovels(7,"A&B? library_id=99 #moon",{userTag:"tea & stars",shelfId:3});
    const request=new URL(String(get.mock.calls[0][0]),"https://fixture.invalid");
    expect(request.searchParams.getAll("library_id")).toEqual(["7"]);
    expect(request.searchParams.get("search")).toBe("A&B? library_id=99 #moon");
    expect(request.searchParams.get("user_tag")).toBe("tea & stars");
    expect(request.searchParams.get("shelf_id")).toBe("3");
  }finally{get.mockRestore();}
});
