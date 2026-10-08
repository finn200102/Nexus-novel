import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ToastProvider } from "../context/ToastContext";
import StoryGuide from "./StoryGuide";
import { insightService } from "../services/insightService";
import type { GuideProjection, StoryGuide as StoryGuideSnapshot } from "../services/insightService";

vi.mock("../services/insightService", async () => {
  const actual = await vi.importActual<typeof import("../services/insightService")>("../services/insightService");
  return {
    ...actual,
    insightService: {
      storyGuideProjection: vi.fn(),
      storyGuide: vi.fn(),
      storyGuideChapterDossier: vi.fn(),
      storyGuideEntityArticle: vi.fn(),
      backfillStoryGuide: vi.fn(),
      regenerateStoryGuide: vi.fn(),
    },
  };
});

const citation = (quote: string) => ({
  chapter: 3,
  quote,
  start_offset: 24,
  end_offset: 48,
  anchor_state: "exact" as const,
});

const dossierProjection: GuideProjection = {
  projection_version: "guide-v2",
  safe_through_chapter: 3,
  coverage: {
    state: "ready",
    analyzed_chapter_count: 3,
    materialized_chapter_count: 3,
    validated_dossier_count: 1,
    ready_dossier_count: 1,
    dossier_count: 1,
    downloaded_chapter_count: 3,
    ambiguous_anchor_count: 0,
    entities: 1,
    characters: 1,
    world_entries: 0,
    assertions: 4,
    relationships: 0,
    citations: 4,
    needs_review: 0,
  },
  overview: { story_so_far: [] },
  characters: [
    {
      id: "character:lyra",
      name: "Lyra Vale",
      kind: "character",
      identity_state: "verified",
      review_state: "approved",
      first_chapter: 1,
      last_chapter: 3,
      aliases: ["The Cartographer"],
      mention_count: 3,
      citations: [citation("Lyra unfolded the map beneath the lantern.")],
      profile: { roles: ["cartographer"], goals: ["find the lost gate"] },
    },
  ],
  world: [],
  relationships: [],
  timeline: [],
  assertions: [],
  chapter_dossiers: [
    {
      chapter: 3,
      summary: [
        {
          id: "summary:3",
          subject: "Chapter 3",
          predicate: "summary",
          object: "Lyra reaches the gate before the storm.",
          state: "established",
          citations: [citation("Lyra reached the gate before the storm arrived.")],
        },
      ],
      point_of_view: [],
      setting: [],
      events: [],
      scenes: [],
      tags: {},
      character_facts: [
        {
          id: "character-fact:lyra-goal",
          subject: "Lyra Vale",
          predicate: "goal",
          object: "find the lost gate",
          chapter: 3,
          state: "active",
          citations: [citation("Her only thought was to find the lost gate.")],
        },
      ],
      consequences: [
        {
          id: "consequence:gate",
          subject: "The gate",
          predicate: "event_consequence",
          object: "The gate seals behind Lyra, cutting off the return path.",
          chapter: 3,
          state: "established",
          citations: [citation("The gate sealed behind her, leaving no road back.")],
        },
      ],
      open_questions: [
        {
          id: "question:map",
          subject: "The map",
          predicate: "open_question",
          object: "Who drew the map that led Lyra to the gate?",
          chapter: 3,
          state: "open",
          citations: [citation("Who had drawn this impossible map?")],
        },
      ],
      takeaways: [
        {
          id: "takeaway:gate",
          subject: "The gate",
          predicate: "takeaway",
          object: "The gate is a one-way threshold, not a safe passage home.",
          chapter: 3,
          state: "important",
          qualifiers: { importance: "central" },
          citations: [citation("The threshold would take her forward, but never back.")],
        },
      ],
      revelations: [
        {
          id: "revelation:map",
          subject: "The map",
          predicate: "revelation",
          object: "The map changes when the storm reaches the gate.",
          chapter: 3,
          state: "established",
          qualifiers: { known_to: "Lyra" },
          citations: [citation("Ink moved across the map as the storm touched the gate.")],
        },
      ],
      character_updates: [
        {
          id: "character-update:lyra",
          subject: "Lyra Vale",
          predicate: "character_update:resolve",
          object: "Lyra chooses to cross the threshold despite losing her way home.",
          chapter: 3,
          state: "changed",
          citations: [citation("Lyra stepped through, knowing the path behind her was gone.")],
        },
      ],
      world_updates: [
        {
          id: "world-update:threshold",
          subject: "The threshold",
          predicate: "world_update:property",
          object: "The threshold responds to the storm and seals itself afterward.",
          chapter: 3,
          state: "confirmed",
          citations: [citation("The threshold answered the storm with a lock of light.")],
        },
      ],
      dossier: {
        status: "ready",
        quality: { assertion_count: 4, citation_count: 4, exact_anchor_count: 4 },
      },
    },
  ],
};

const snapshot: StoryGuideSnapshot = {
  chapters_analyzed: 3,
  through_chapter: 3,
  guide_status: "ready",
  characters: [],
  chapters: [],
};

const renderGuide = () =>
  render(
    <MemoryRouter initialEntries={["/story-guide/42"]}>
      <ToastProvider>
        <Routes>
          <Route path="/story-guide/:metadataId" element={<StoryGuide />} />
        </Routes>
      </ToastProvider>
    </MemoryRouter>,
  );

describe("StoryGuide richer chapter dossiers", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(insightService.storyGuideProjection).mockResolvedValue(dossierProjection);
    vi.mocked(insightService.storyGuide).mockResolvedValue(snapshot);
  });

  it("renders cited character developments, consequences, and open questions", async () => {
    renderGuide();

    await screen.findByRole("heading", { name: /story guide/i });
    fireEvent.click(within(screen.getByRole("navigation", { name: /story guide sections/i })).getByRole("button", { name: /^chapters/i }));

    await screen.findByRole("heading", { name: /recaps, changes, and source evidence/i });
    const dossier = document.querySelector<HTMLElement>("section.novel-insights__guide .story-guide-page__chapter-list > article");
    expect(dossier).not.toBeNull();

    expect(within(dossier!).getByRole("heading", { name: "Character facts" })).toBeTruthy();
    expect(within(dossier!).getByText("Lyra Vale · goal")).toBeTruthy();
    expect(within(dossier!).getByText("find the lost gate")).toBeTruthy();

    expect(within(dossier!).getByRole("heading", { name: "Consequences and changes" })).toBeTruthy();
    expect(within(dossier!).getByText("The gate seals behind Lyra, cutting off the return path.")).toBeTruthy();

    expect(within(dossier!).getByRole("heading", { name: "Open questions" })).toBeTruthy();
    expect(within(dossier!).getByText("Who drew the map that led Lyra to the gate?")).toBeTruthy();

    expect(within(dossier!).getByRole("heading", { name: "What matters" })).toBeTruthy();
    expect(within(dossier!).getByText("The gate is a one-way threshold, not a safe passage home.")).toBeTruthy();

    expect(within(dossier!).getByRole("heading", { name: "Revelations" })).toBeTruthy();
    expect(within(dossier!).getByText("The map changes when the storm reaches the gate.")).toBeTruthy();

    expect(within(dossier!).getByRole("heading", { name: "Character updates" })).toBeTruthy();
    expect(within(dossier!).getByText("Lyra chooses to cross the threshold despite losing her way home.")).toBeTruthy();

    expect(within(dossier!).getByRole("heading", { name: "World updates" })).toBeTruthy();
    expect(within(dossier!).getByText("The threshold responds to the storm and seals itself afterward.")).toBeTruthy();
  });

  it("keeps evidence attached to each rendered dossier fact", async () => {
    renderGuide();

    await screen.findByRole("heading", { name: /story guide/i });
    fireEvent.click(within(screen.getByRole("navigation", { name: /story guide sections/i })).getByRole("button", { name: /^chapters/i }));
    await screen.findByRole("heading", { name: /recaps, changes, and source evidence/i });
    const dossier = document.querySelector<HTMLElement>("section.novel-insights__guide .story-guide-page__chapter-list > article");
    expect(dossier).not.toBeNull();

    const evidenceSummaries = within(dossier!).getAllByText(/Chapter evidence · 1/);
    expect(evidenceSummaries).toHaveLength(8);
    expect(within(dossier!).getByText(/The gate sealed behind her, leaving no road back\./)).toBeTruthy();
    expect(within(dossier!).getByText(/Who had drawn this impossible map\?/)).toBeTruthy();
  });
});
