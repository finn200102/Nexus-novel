import {act} from "react";
import {createRoot} from "react-dom/client";
import {afterEach,expect,it,vi} from "vitest";
import AccountDataPanel from "./AccountDataPanel";
import {userDataService} from "../../services/userDataService";

vi.mock("../../context/useLibraryContext",()=>({useLibraryContext:()=>({refreshLibraries:async()=>undefined})}));
vi.mock("../../context/useToast",()=>({useToast:()=>({addToast:vi.fn()})}));
vi.mock("../../services/userDataService",()=>({userDataService:{importData:vi.fn(),exportData:vi.fn()}}));
const host=document.createElement("div");document.body.append(host);
let root:ReturnType<typeof createRoot>|undefined;
afterEach(()=>{if(root)act(()=>root!.unmount());root=undefined;host.innerHTML="";vi.clearAllMocks();});

it("reports paused smart rules with their review location and preserves conflicting local choices",async()=>{
  vi.mocked(userDataService.importData).mockResolvedValue({format:"nexus-user-export",version:1,libraries:[],saved_searches:[],
    summary:{smart_shelves_created:1,smart_shelves_conflicts:1},smart_shelves:[
      {name:"Imported reading",status:"created",needs_review:true},
      {name:"My existing rule",status:"conflict"},
    ]});
  root=createRoot(host);await act(async()=>root!.render(<AccountDataPanel/>));
  const input=host.querySelector<HTMLInputElement>('input[type="file"]')!;
  Object.defineProperty(input,"files",{configurable:true,value:[{text:async()=>JSON.stringify({format:"nexus-user-export",version:1,libraries:[]})}]});
  await act(async()=>{input.dispatchEvent(new Event("change",{bubbles:true}));});
  expect(host.textContent).toContain("Imported reading” is paused for review");
  expect(host.textContent).toContain("Organize menu");
  expect(host.textContent).toContain("My existing rule” already has different criteria; kept your version");
});

it('reports unavailable private originals and retained destination conflicts without inventing source links',async()=>{
 const base={url:null,title:'Private notebook',status:'created' as const,reason:null,follow_state:null,progress:null,history:{added:0,updated:0,unchanged:0},annotations:{added:0,duplicate:0,deferred:0}};
 vi.mocked(userDataService.importData).mockResolvedValue({format:'nexus-user-export',version:2,saved_searches:[],summary:{novels_created:1,novels_conflicts:1},libraries:[{name:'Private books',status:'existing',novels:[{...base,novel_id:7,original_status:'unavailable'},{...base,status:'conflict',portable_link_id:3,title:'Old private book',reason:'The original destination was deleted. Imported material is retained for review.'}]}]});
 root=createRoot(host);await act(async()=>root!.render(<AccountDataPanel/>));
 const input=host.querySelector<HTMLInputElement>('input[type="file"]')!;
 Object.defineProperty(input,'files',{configurable:true,value:[{text:async()=>JSON.stringify({format:'nexus-user-export',version:2,libraries:[]})}]});
 await act(async()=>{input.dispatchEvent(new Event('change',{bubbles:true}));});
 expect(host.textContent).toContain('“Private notebook” is retained in Private books. Its original content is unavailable here.');
 expect(host.textContent).toContain('Old private book (Private books): The original destination was deleted. Imported material is retained for review.');
 expect(host.textContent).toContain('Private story destinations needing review');
 expect(host.querySelector('a')).toBeNull();
});

it('never submits a previous account file when reading it finishes after an account switch',async()=>{
 const {activateAccountStorage}=await import('../../services/accountStorage');activateAccountStorage(551);
 let finish!:(value:string)=>void;const pending=new Promise<string>(resolve=>{finish=resolve;});
 root=createRoot(host);await act(async()=>root!.render(<AccountDataPanel/>));
 const input=host.querySelector<HTMLInputElement>('input[type="file"]')!;Object.defineProperty(input,'files',{configurable:true,value:[{text:()=>pending}]});
 act(()=>input.dispatchEvent(new Event('change',{bubbles:true})));
 await act(async()=>activateAccountStorage(552));
 await act(async()=>finish(JSON.stringify({format:'nexus-user-export',version:2,libraries:[{name:'Previous private library',novels:[]}]})));
 expect(userDataService.importData).not.toHaveBeenCalled();expect(host.textContent).not.toContain('Previous private library');
 activateAccountStorage(null);
});
