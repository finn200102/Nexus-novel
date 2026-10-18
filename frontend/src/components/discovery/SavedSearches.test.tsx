import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SavedSearches } from "./SavedSearches";
import { savedSearchService, type SavedSearch, type SavedSearchDefinition } from "../../services/savedSearchService";
import { EMPTY_DISCOVERY_FILTERS } from "../../services/discoveryFilters";
import { activateAccountStorage } from "../../services/accountStorage";

vi.mock("../../services/savedSearchService", async () => ({...await vi.importActual("../../services/savedSearchService"),savedSearchService:{list:vi.fn(),create:vi.fn(),update:vi.fn(),remove:vi.fn()}}));
const definition:SavedSearchDefinition={version:1,scope:"catalog",q:"dragon & moon",site:"fanfiction",similar_to:912,filters:{...EMPTY_DISCOVERY_FILTERS,tag:["Adventure"],crossover:"true",sortBy:"favorites"}};
const saved:SavedSearch={id:4,name:"Evening",definition,filters:definition.filters,revision:"a".repeat(64),needs_review:false,warnings:[],notify_on_match:false,alert_state:"off",created_at:"2026-10-16T00:00:00",updated_at:"2026-10-16T00:00:00"};
function Location(){const location=useLocation();return <output data-testid="location">{location.pathname}{location.search}</output>;}
function mount(){return render(<MemoryRouter><SavedSearches definition={definition} saveRequest={0}/><Location/></MemoryRouter>);}
beforeEach(()=>{vi.clearAllMocks();activateAccountStorage(101);vi.mocked(savedSearchService.list).mockResolvedValue([]);});

describe("saved catalog queries",()=>{
  it("saves all query criteria through a reviewed dialog",async()=>{
    vi.mocked(savedSearchService.create).mockResolvedValue(saved); mount();
    await screen.findByText("No saved searches yet.");
    fireEvent.click(screen.getByRole("button",{name:"Save current search"}));
    const dialog=screen.getByRole("dialog",{name:"Save search"});
    expect(within(dialog).getByLabelText("Text query")).toHaveValue("dragon & moon");
    expect(within(dialog).getByLabelText("Source")).toHaveValue("fanfiction");
    fireEvent.change(within(dialog).getByRole("textbox",{name:/Search name/}),{target:{value:"Evening"}});
    fireEvent.click(within(dialog).getByRole("button",{name:"Save reviewed search"}));
    await waitFor(()=>expect(savedSearchService.create).toHaveBeenCalledWith("Evening",definition));
    expect(await screen.findByText(/Saved “Evening” with its query/)).toBeInTheDocument();
  });
  it("opens the exact source, text, similarity and sort",async()=>{
    vi.mocked(savedSearchService.list).mockResolvedValue([saved]); mount();
    fireEvent.click(await screen.findByRole("button",{name:"Open Evening"}));
    const href=new URL(screen.getByTestId("location").textContent!,"https://nexus.test");
    expect(href.pathname).toBe("/discover/fanfiction");expect(href.searchParams.get("q")).toBe(definition.q);
    expect(href.searchParams.get("similar_to")).toBe("912");expect(JSON.parse(href.searchParams.get("filters")!)).toEqual(definition.filters);
  });
  it("requires review of legacy searches and retains explicit failed-edit state",async()=>{
    const legacy={...saved,needs_review:true,warnings:["Confirm the original query and source."],notify_on_match:true,alert_state:"paused" as const};
    vi.mocked(savedSearchService.list).mockResolvedValue([legacy]);vi.mocked(savedSearchService.update).mockRejectedValue(new Error("changed"));mount();
    expect(await screen.findByRole("button",{name:"Open Evening"})).toBeDisabled();
    fireEvent.click(screen.getByRole("button",{name:"Review Evening"}));
    fireEvent.change(screen.getByLabelText("Text query"),{target:{value:"reviewed query"}});
    fireEvent.click(screen.getByRole("button",{name:"Save reviewed search"}));
    await waitFor(()=>expect(savedSearchService.update).toHaveBeenCalledWith(legacy,"Evening",{...definition,q:"reviewed query"}));
    expect(await screen.findByText(/This search could not be saved/)).toBeVisible();
    expect(screen.getByRole("dialog",{name:"Review saved search"})).toBeVisible();
  });
  it("reviews deletion and sends the displayed revision",async()=>{
    vi.mocked(savedSearchService.list).mockResolvedValue([saved]);vi.mocked(savedSearchService.remove).mockResolvedValue(undefined);mount();
    fireEvent.click(await screen.findByRole("button",{name:"Delete Evening"}));expect(savedSearchService.remove).not.toHaveBeenCalled();
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button",{name:"Delete saved search"}));
    await waitFor(()=>expect(savedSearchService.remove).toHaveBeenCalledWith(saved));
    expect(await screen.findByText("Deleted “Evening”.")).toBeInTheDocument();
  });
  it("discards a late private list after switching accounts",async()=>{
    let resolve!:(rows:SavedSearch[])=>void;
    vi.mocked(savedSearchService.list).mockImplementationOnce(()=>new Promise(done=>{resolve=done;})).mockResolvedValueOnce([]);
    mount();await act(async()=>{activateAccountStorage(102);});await screen.findByText("No saved searches yet.");
    await act(async()=>{resolve([saved]);});expect(screen.queryByText("Evening")).not.toBeInTheDocument();
  });
});
