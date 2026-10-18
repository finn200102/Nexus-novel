import {render,screen} from "@testing-library/react";
import {MemoryRouter} from "react-router-dom";
import {describe,expect,it,vi} from "vitest";
import Integrations from "./Integrations";
import {ToastProvider} from "../context/ToastContext";
import {adminIntegrationService} from "../services/adminIntegrationService";
vi.mock("../services/adminIntegrationService",()=>({adminIntegrationService:{mergeReviews:vi.fn(async()=>[{id:1,target_novel_id:7,target_title:"Possible edition",status:"pending",confidence:0.7,match_reasons:["Similar title"],conflicts:[],source:{site:"royalroad",canonical_url:"https://example.invalid/story",novel_id:4}},{id:2,target_novel_id:8,target_title:"Legacy approved suggestion",status:"approved",confidence:0.8,match_reasons:[],conflicts:[],source:{site:"fanfiction",canonical_url:"https://example.invalid/other",novel_id:5}}]),webhooks:vi.fn(async()=>[]),decideMerge:vi.fn()}}));
describe("legacy catalog review safety",()=>{
 it("keeps old duplicate suggestions read-only rather than offering unsafe merge decisions",async()=>{
  render(<MemoryRouter><ToastProvider><Integrations/></ToastProvider></MemoryRouter>);
  await screen.findByText("royalroad → Possible edition");expect(screen.getByRole("heading",{name:"Legacy duplicate history"})).toBeTruthy();expect(screen.getByText(/older suggestions are read-only/)).toBeTruthy();expect(screen.queryByRole("button",{name:/Approve|Reject|Revert/})).toBeNull();expect(adminIntegrationService.decideMerge).not.toHaveBeenCalled();
 });
});
