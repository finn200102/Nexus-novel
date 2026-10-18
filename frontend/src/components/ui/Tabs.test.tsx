import {act,fireEvent,render,screen} from "@testing-library/react";
import {afterEach,beforeEach,describe,expect,it,vi} from "vitest";
import {useState} from "react";
import {Tabs} from "./Tabs";
const items=[{value:"about",label:"About"},{value:"disabled",label:"Disabled",disabled:true},{value:"history",label:"Reading history"}];
let width=200,resize:()=>void,disconnect:ReturnType<typeof vi.fn>;
beforeEach(()=>{
  width=200;disconnect=vi.fn();
  vi.stubGlobal("ResizeObserver",class{constructor(callback:()=>void){resize=callback;}observe(){}disconnect=disconnect;});
  vi.spyOn(HTMLElement.prototype,"clientWidth","get").mockImplementation(function(this:HTMLElement){return this.classList.contains("ui-tabs__scroller")?width:0;});
  vi.spyOn(HTMLElement.prototype,"scrollWidth","get").mockImplementation(function(this:HTMLElement){return this.classList.contains("ui-tabs__scroller")?800:0;});
  vi.spyOn(HTMLElement.prototype,"getBoundingClientRect").mockImplementation(function(this:HTMLElement){
    if(this.classList.contains("ui-tabs__scroller"))return {left:100,right:100+width,width} as DOMRect;
    const owner=this.closest<HTMLElement>(".ui-tabs__scroller"),start=this.textContent==="Reading history"?500:100;
    const left=start-(owner?.scrollLeft||0);return{left,right:left+120,width:120} as DOMRect;
  });
});
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals();});
describe("horizontal selected-tab reveal",()=>{
  it("reveals a directly selected tab on mount without changing focus or vertical scroll",()=>{
    const focus=document.createElement("input");document.body.append(focus);focus.focus();
    const vertical=window.scrollY;
    const view=render(<Tabs label="Sections" items={items} value="history" onChange={()=>undefined}/>);
    expect(view.container.querySelector(".ui-tabs__scroller")!.scrollLeft).toBe(336);
    expect(document.activeElement).toBe(focus);expect(window.scrollY).toBe(vertical);focus.remove();
  });
  it("reveals on selection and container resize, then disconnects safely",()=>{
    const view=render(<Tabs label="Sections" items={items} value="about" onChange={()=>undefined}/>);
    const container=view.container.querySelector<HTMLElement>(".ui-tabs__scroller")!;expect(container.scrollLeft).toBe(0);
    view.rerender(<Tabs label="Sections" items={items} value="history" onChange={()=>undefined}/>);expect(container.scrollLeft).toBe(336);
    width=160;act(()=>resize());expect(container.scrollLeft).toBe(376);
    view.unmount();expect(disconnect).toHaveBeenCalled();
  });
  it("keeps automatic keyboard activation, skips disabled tabs and prevents focus scroll",()=>{
    function Example(){const[value,set]=useState("about");return <Tabs label="Sections" items={items} value={value} onChange={set}/>;}
    render(<Example/>);const history=screen.getByRole("tab",{name:"Reading history"});const focus=vi.spyOn(history,"focus");
    fireEvent.keyDown(screen.getByRole("tab",{name:"About"}),{key:"ArrowRight"});
    expect(history).toHaveAttribute("aria-selected","true");expect(focus).toHaveBeenCalledWith({preventScroll:true});
    fireEvent.keyDown(history,{key:"ArrowRight"});expect(screen.getByRole("tab",{name:"About"})).toHaveAttribute("aria-selected","true");
    fireEvent.keyDown(screen.getByRole("tablist"),{key:"End"});expect(history).toHaveAttribute("aria-selected","true");
  });
  it("keeps an oversized label aligned consistently instead of alternating edges",()=>{
    width=100;
    const view=render(<Tabs label="Sections" items={items} value="history" onChange={()=>undefined}/>);
    const container=view.container.querySelector<HTMLElement>(".ui-tabs__scroller")!;
    const first=container.scrollLeft;act(()=>resize());act(()=>resize());
    expect(first).toBe(384);expect(container.scrollLeft).toBe(first);
  });
  it("ignores keyboard navigation when no enabled tab exists",()=>{
    const change=vi.fn(),view=render(<Tabs label="Empty" items={[]} value="missing" onChange={change}/>);
    fireEvent.keyDown(screen.getByRole("tablist"),{key:"ArrowRight"});
    view.rerender(<Tabs label="Empty" items={items.map(item=>({...item,disabled:true}))} value="history" onChange={change}/>);
    fireEvent.keyDown(screen.getByRole("tablist"),{key:"Home"});expect(change).not.toHaveBeenCalled();
  });
});
