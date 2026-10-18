import {act,fireEvent,render,screen,waitFor} from "@testing-library/react";
import {beforeEach,describe,expect,it,vi} from "vitest";
import PronunciationEditor from "./PronunciationEditor";
import {pronunciationService,type PronunciationProfile} from "../../services/pronunciationService";
import {activateAccountStorage} from "../../services/accountStorage";
vi.mock("../../services/pronunciationService",async original=>({...await original<typeof import("../../services/pronunciationService")>(),pronunciationService:{get:vi.fn(),save:vi.fn()}}));
const profile=(story=false):PronunciationProfile=>({scope:story?"pronunciation:11":"pronunciation",revision:2,rules:[],account_rules:story?[{source:"Nexus",spoken:"Nek-sus"}]:[],inherit_account:story,effective_rules:story?[{source:"Nexus",spoken:"Nek-sus"}]:[],effective_version:story?"account-version":null});
const open=()=>fireEvent.click(screen.getByText("Pronunciation",{exact:true}));
describe("pronunciation editor",()=>{
  beforeEach(()=>{vi.clearAllMocks();activateAccountStorage(7);vi.mocked(pronunciationService.get).mockResolvedValue(profile());});
  it("previews unsaved literal spelling and saves with a revision without generating audio",async()=>{
    const onReady=vi.fn();render(<PronunciationEditor onReady={onReady}/>);open();
    await waitFor(()=>expect(onReady).toHaveBeenLastCalledWith({version:null,rules:[]}));
    fireEvent.click(screen.getByRole("button",{name:"Add pronunciation"}));
    fireEvent.change(screen.getByLabelText("Written form 1"),{target:{value:"Nexus"}});
    fireEvent.change(screen.getByLabelText("Spoken form 1"),{target:{value:"Nek-sus"}});
    fireEvent.change(screen.getByLabelText("Pronunciation preview text"),{target:{value:"Nexus and nexus"}});
    expect(screen.getByText(/Nek-sus and nexus/)).toBeInTheDocument();
    expect(onReady).toHaveBeenLastCalledWith(null);
    const saved={...profile(),revision:3,rules:[{source:"Nexus",spoken:"Nek-sus"}],effective_rules:[{source:"Nexus",spoken:"Nek-sus"}],effective_version:"saved-version"};
    vi.mocked(pronunciationService.save).mockResolvedValue(saved);
    fireEvent.click(screen.getByRole("button",{name:"Save pronunciations"}));
    await waitFor(()=>expect(pronunciationService.save).toHaveBeenCalledWith(expect.objectContaining({expected_revision:2,operation_id:expect.any(String),rules:[{source:"Nexus",spoken:"Nek-sus"}]}),undefined));
    await waitFor(()=>expect(onReady).toHaveBeenLastCalledWith({version:"saved-version",rules:saved.rules}));
  });
  it("retains conflicting edits until a reviewed reload",async()=>{
    render(<PronunciationEditor/>);open();
    await waitFor(()=>expect(screen.getByRole("button",{name:"Add pronunciation"})).toBeEnabled());
    fireEvent.click(screen.getByRole("button",{name:"Add pronunciation"}));
    fireEvent.change(screen.getByLabelText("Written form 1"),{target:{value:"Alice"}});
    fireEvent.change(screen.getByLabelText("Spoken form 1"),{target:{value:"A-leece"}});
    vi.mocked(pronunciationService.save).mockRejectedValue(new Error("revision conflict"));
    fireEvent.click(screen.getByRole("button",{name:"Save pronunciations"}));
    await screen.findByText(/Your edits are retained/);
    expect(screen.getByLabelText("Spoken form 1")).toHaveValue("A-leece");
    fireEvent.click(screen.getByRole("button",{name:"Reload saved pronunciations"}));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(pronunciationService.get).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button",{name:"Reload saved entries"}));
    await waitFor(()=>expect(screen.queryByLabelText("Written form 1")).not.toBeInTheDocument());
    expect(pronunciationService.get).toHaveBeenCalledTimes(2);
  });
  it("previews inherited rules accurately after removing a story override",async()=>{
    vi.mocked(pronunciationService.get).mockResolvedValue({...profile(true),rules:[{source:"Nexus",spoken:"Story voice"}],effective_rules:[{source:"Nexus",spoken:"Story voice"}]});
    render(<PronunciationEditor novelId={11}/>);open();
    await screen.findByLabelText("Written form 1");
    fireEvent.click(screen.getByRole("button",{name:"Remove pronunciation 1"}));
    fireEvent.change(screen.getByLabelText("Pronunciation preview text"),{target:{value:"Nexus"}});
    expect(screen.getByText(/Nek-sus/)).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Include account pronunciations"));
    expect(screen.getByText(/^Nexus$/)).toBeInTheDocument();
  });
  it("discards a delayed former account profile",async()=>{
    let finish!:(value:PronunciationProfile)=>void;
    vi.mocked(pronunciationService.get).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;})).mockResolvedValue(profile());
    render(<PronunciationEditor/>);open();
    await act(async()=>{activateAccountStorage(8);});
    await waitFor(()=>expect(pronunciationService.get).toHaveBeenCalledTimes(2));
    await act(async()=>{finish({...profile(),rules:[{source:"Private old name",spoken:"Private old voice"}]});});
    expect(screen.queryByDisplayValue("Private old name")).not.toBeInTheDocument();
  });
  it("keeps invalid markup edits visible without rendering them as provider input",async()=>{
    render(<PronunciationEditor/>);open();
    await waitFor(()=>expect(screen.getByRole("button",{name:"Add pronunciation"})).toBeEnabled());
    fireEvent.click(screen.getByRole("button",{name:"Add pronunciation"}));
    fireEvent.change(screen.getByLabelText("Written form 1"),{target:{value:"<speak>"}});
    fireEvent.change(screen.getByLabelText("Spoken form 1"),{target:{value:"Say"}});
    fireEvent.change(screen.getByLabelText("Pronunciation preview text"),{target:{value:"<speak>"}});
    expect(screen.getByRole("button",{name:"Save pronunciations"})).toBeDisabled();
    expect(screen.getByText(/Use plain pronunciation text/)).toBeInTheDocument();
    expect(pronunciationService.save).not.toHaveBeenCalled();
  });

  it("reuses its operation ID after a lost save acknowledgement",async()=>{
    render(<PronunciationEditor/>);open();
    await waitFor(()=>expect(screen.getByRole("button",{name:"Add pronunciation"})).toBeEnabled());
    fireEvent.click(screen.getByRole("button",{name:"Add pronunciation"}));
    fireEvent.change(screen.getByLabelText("Written form 1"),{target:{value:"Anna"}});
    fireEvent.change(screen.getByLabelText("Spoken form 1"),{target:{value:"AH nah"}});
    vi.mocked(pronunciationService.save).mockRejectedValueOnce(new Error("Response lost")).mockResolvedValue({...profile(),revision:3,rules:[{source:"Anna",spoken:"AH nah"}],effective_rules:[{source:"Anna",spoken:"AH nah"}],effective_version:"saved"});
    fireEvent.click(screen.getByRole("button",{name:"Save pronunciations"}));
    await screen.findByText(/Your edits are retained/);
    fireEvent.click(screen.getByRole("button",{name:"Save pronunciations"}));
    await waitFor(()=>expect(pronunciationService.save).toHaveBeenCalledTimes(2));
    const calls=vi.mocked(pronunciationService.save).mock.calls;
    expect(calls[1][0]).toEqual(calls[0][0]);
    await screen.findByText(/Pronunciations saved for new audio/);
  });

});
