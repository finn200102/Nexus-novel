import {act,render,screen,fireEvent,waitFor} from "@testing-library/react";
import {describe,it,expect,vi} from "vitest";
import AudioPartRepair from "./AudioPartRepair";
import {audioService} from "../../services/audioService";
vi.mock("../../services/audioService",()=>({audioService:{parts:vi.fn(),retryPart:vi.fn()}}));
describe("individual narration repair",()=>{
  it("clears old passages and replacement confirmation when the recording changes",async()=>{
    vi.mocked(audioService.parts).mockResolvedValue({parts:[{part_index:4,text:"Old recording words",status:"completed"}]});
    const view=render(<AudioPartRepair jobId={8} onRepaired={vi.fn()}/>);
    fireEvent.click(screen.getByText("Repair individual narration passages"));
    fireEvent.click(await screen.findByRole("button",{name:"Regenerate passage 5"}));
    expect(screen.getByRole("dialog")).toBeVisible();
    vi.mocked(audioService.parts).mockResolvedValue({parts:[{part_index:0,text:"New recording words",status:"completed"}]});
    view.rerender(<AudioPartRepair jobId={9} onRepaired={vi.fn()}/>);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByText(/Old recording words/)).toBeNull();
    fireEvent.click(screen.getByText("Repair individual narration passages"));
    expect(await screen.findByText(/New recording words/)).toBeVisible();
    expect(screen.queryByRole("button",{name:"Regenerate passage 5"})).toBeNull();
  });
  it("ignores a repair response after switching recordings",async()=>{
    vi.mocked(audioService.parts).mockResolvedValue({parts:[{part_index:0,text:"Old recording",status:"completed"}]});
    let finish!:(value:never)=>void;
    vi.mocked(audioService.retryPart).mockImplementation(()=>new Promise(resolve=>{finish=resolve;}));
    const done=vi.fn();
    const view=render(<AudioPartRepair jobId={8} onRepaired={done}/>);
    fireEvent.click(screen.getByText("Repair individual narration passages"));
    fireEvent.click(await screen.findByRole("button",{name:"Regenerate passage 1"}));
    fireEvent.click(screen.getByRole("button",{name:/^Regenerate passage$/}));
    view.rerender(<AudioPartRepair jobId={9} onRepaired={done}/>);
    await act(async()=>finish({id:8} as never));
    expect(done).not.toHaveBeenCalled();
  });
  it("requires explicit replacement confirmation and sends the selected passage only",async()=>{
    vi.mocked(audioService.parts).mockResolvedValue({parts:[{part_index:0,text:"Opening words",status:"completed"},{part_index:1,text:"Later words",status:"completed"}]});
    vi.mocked(audioService.retryPart).mockResolvedValue({id:8} as never);
    const done=vi.fn();render(<AudioPartRepair jobId={8} onRepaired={done}/>);
    fireEvent.click(screen.getByText("Repair individual narration passages"));
    fireEvent.click(await screen.findByRole("button",{name:"Regenerate passage 2"}));
    expect(audioService.retryPart).not.toHaveBeenCalled();
    expect(screen.getByText(/other completed passages are kept/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button",{name:/^Regenerate passage$/}));
    await waitFor(()=>expect(audioService.retryPart).toHaveBeenCalledWith(8,1));
    expect(done).toHaveBeenCalledOnce();
  });
});
