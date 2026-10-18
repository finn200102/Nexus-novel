import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "./apiClient";
import { defaultLibraryDefinition, libraryViewService, ownedDefinitionKey } from "./libraryViewService";
vi.mock("./apiClient",()=>({default:{post:vi.fn(),get:vi.fn()}}));
describe("owned library query transport",()=>{
 it("does not confirm a different literal query after an interrupted save",()=>{const value={...defaultLibraryDefinition(),q:" moon "};expect(ownedDefinitionKey(value)).not.toBe(ownedDefinitionKey({...value,q:"moon"}));expect(ownedDefinitionKey(value)).not.toBe(ownedDefinitionKey({...value,q:"moon "}));});
 beforeEach(()=>{vi.clearAllMocks();vi.mocked(apiClient.post).mockResolvedValue({data:{total:120}});});
 it("sends complete signed-free criteria as JSON rather than interpolating title/author text into a URL",async()=>{const definition={...defaultLibraryDefinition([1]),q:"A&B + maps?",source:"local",follow_states:["reading" as const],min_rating:4};const controller=new AbortController();await libraryViewService.preview(definition,100,50,controller.signal);expect(apiClient.post).toHaveBeenCalledWith("/library-views/preview",{definition,offset:100,limit:50},{signal:controller.signal});});
 it("compares exact normalized criteria independently of property/selection ordering",()=>{const value=defaultLibraryDefinition([2,1]);expect(ownedDefinitionKey(value)).toBe(ownedDefinitionKey({...value,library_ids:[1,2]}));expect(ownedDefinitionKey(value)).not.toBe(ownedDefinitionKey({...value,source:"local"}));});
});
