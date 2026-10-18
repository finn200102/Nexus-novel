import {StrictMode} from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ScrapeJobs from "./ScrapeJobs";
import { catalogScrapeService } from "../services/catalogScrapeService";

vi.mock("../services/catalogScrapeService", () => ({ catalogScrapeService: {
  capabilities: vi.fn(), definitions: vi.fn(), definition:vi.fn(), activeJobs:vi.fn(), job:vi.fn(), candidates:vi.fn(), cancel:vi.fn(), run:vi.fn(), pause:vi.fn(),resume:vi.fn(),remove:vi.fn(), preview: vi.fn(), create: vi.fn(), update: vi.fn(),
} }));
vi.mock("../context/useLibraryContext", () => ({ useLibraryContext: () => ({ activeLibraryId: 1 }) }));
vi.mock("../services/discoveryService", () => ({ discoveryService: { getFandoms: vi.fn().mockResolvedValue([]) } }));

const capability = { site: "fanfiction", name: "FanFiction.net", adapter_version: 1,
  modes: ["top_rated", "newest", "crossover", "custom_urls"], filters: ["fandoms", "crossover"],
  remote_filters: [], local_filters: [], rate_limit: "1 request/second" };

async function open() {
  render(<MemoryRouter><ScrapeJobs /></MemoryRouter>);
  await screen.findByRole("button", { name: "Top rated" });
}

describe("catalog job configuration", () => {
  beforeEach(() => {
    localStorage.clear();vi.clearAllMocks();
    vi.spyOn(window, "scrollTo").mockImplementation(() => {});
    vi.spyOn(window, "requestAnimationFrame").mockImplementation(callback => { callback(0); return 1; });
    vi.mocked(catalogScrapeService.capabilities).mockResolvedValue({ sources: [capability], default_site: "fanfiction", version: 2 });
    vi.mocked(catalogScrapeService.definitions).mockResolvedValue([]);
    vi.mocked(catalogScrapeService.preview).mockRejectedValue(new Error("fixture stops before source fetch"));
  });

  it("combines crossover with top rated and preserves it when ranking changes", async () => {
    await open();
    expect(screen.queryByRole("button", { name: "Crossover" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Top rated" }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Crossovers only/ }));
    fireEvent.click(screen.getByRole("button", { name: "Preview results" }));
    await waitFor(() => expect(catalogScrapeService.preview).toHaveBeenCalledWith("fanfiction", expect.objectContaining({ mode: "top_rated", crossover: true })));
    fireEvent.click(screen.getByRole("button", { name: "Newest" }));
    expect(screen.getByRole("checkbox", { name: /Crossovers only/ })).toBeChecked();
  });

  it("a second fandom enables crossover, and clearing crossover clears the second fandom", async () => {
    await open();
    fireEvent.change(screen.getByLabelText("Fandom B"), { target: { value: "Naruto" } });
    expect(screen.getByRole("checkbox", { name: /Crossovers only/ })).toBeChecked();
    fireEvent.click(screen.getByRole("checkbox", { name: /Crossovers only/ }));
    expect(screen.getByLabelText("Fandom B")).toHaveValue("");
  });

  it("edits an old crossover job in place and retains an untouched calendar schedule", async () => {
    vi.mocked(catalogScrapeService.definitions).mockResolvedValue([{ id: 9, name: "Legacy crossover", site: "fanfiction", enabled: true,
      definition_revision:"a".repeat(64),control_state:"review_required",schedule: { kind: "weekly" }, query: { mode: "crossover", crossover: true, sort: "favorites" } as never }]);
    vi.mocked(catalogScrapeService.preview).mockImplementation(async(_site,query)=>({query,capabilities:capability,source_url:"https://fixture.invalid/list",estimated_pages:1,matched_count:0,preview:[],warnings:[],review_token:"reviewed"}));
    vi.mocked(catalogScrapeService.update).mockResolvedValue({id:9,name:"Legacy crossover",site:"fanfiction",enabled:true,query:{} as never});
    vi.mocked(catalogScrapeService.definition).mockResolvedValue({id:9,name:"Legacy crossover",site:"fanfiction",enabled:true,query:{} as never});
    await open();
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    expect(screen.getByRole("checkbox", { name: /Crossovers only/ })).toBeChecked();
    fireEvent.click(screen.getByRole("button",{name:"Preview results"}));
    await waitFor(()=>expect(screen.getByRole("button",{name:"Save changes"})).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    fireEvent.click(screen.getByRole("button",{name:"Confirm catalog update"}));
    await waitFor(() => expect(catalogScrapeService.update).toHaveBeenCalledWith(9, expect.objectContaining({ name: "Legacy crossover", query: expect.objectContaining({ mode: "most_favorited", crossover: true }) })));
    expect(vi.mocked(catalogScrapeService.update).mock.calls[0][1]).not.toHaveProperty("schedule_interval_minutes");
    expect(catalogScrapeService.create).not.toHaveBeenCalled();
  });

  it("backfill exposes bounded requests and pages separately from ranking", async () => {
    await open();
    fireEvent.change(screen.getByLabelText("Collection scope"), { target: { value: "backfill" } });
    expect(screen.getByLabelText("Listing requests per day")).toHaveValue(300);
    expect(screen.getByLabelText("Pages per run")).toHaveValue(20);
    fireEvent.click(screen.getByRole("button", { name: "Top rated" }));
    fireEvent.click(screen.getByRole("button", { name: "Preview results" }));
    await waitFor(() => expect(catalogScrapeService.preview).toHaveBeenCalledWith("fanfiction", expect.objectContaining({ run_mode: "backfill", daily_request_budget: 300, max_pages_per_run: 20, max_pages: 1000, mode: "top_rated" })));
  });
});

it("restarts catalog loading in StrictMode and ignores the discarded effect response", async () => {
  let finish!: (value: Awaited<ReturnType<typeof catalogScrapeService.capabilities>>) => void;
  vi.mocked(catalogScrapeService.definitions).mockResolvedValue([]);
  vi.mocked(catalogScrapeService.capabilities)
    .mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }))
    .mockResolvedValue({sources:[capability],default_site:"fanfiction",version:2});
  render(<StrictMode><MemoryRouter><ScrapeJobs /></MemoryRouter></StrictMode>);
  await screen.findByRole("button", {name:"Top rated"});
  expect(catalogScrapeService.capabilities).toHaveBeenCalledTimes(2);
  await act(async()=>finish({sources:[{...capability,name:"Discarded response"}],default_site:"fanfiction",version:2}));
  expect(screen.queryByRole("button",{name:/Discarded response/})).toBeNull();
  expect(screen.getByRole("button",{name:/FanFiction.net/})).toBeVisible();
});
