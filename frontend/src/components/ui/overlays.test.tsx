import { useState } from "react";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { Button, Cover, Dialog, ListRow, Menu, Progress, Sheet, Tabs, coverHueIndex } from ".";

function DialogHarness({ onClose }: { onClose?: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <Button onClick={() => setOpen(true)}>Open</Button>
      <Dialog
        open={open}
        onClose={() => {
          onClose?.();
          setOpen(false);
        }}
        title="Delete shelf?"
        description="Stories stay in your library."
        actions={<Button onClick={() => setOpen(false)}>Cancel</Button>}
      />
    </div>
  );
}

describe("Dialog", () => {
  it("is labelled, traps focus, closes on Escape and restores focus", async () => {
    const user = userEvent.setup();
    render(<DialogHarness />);
    const opener = screen.getByRole("button", { name: "Open" });
    await user.click(opener);
    const dialog = screen.getByRole("dialog", { name: "Delete shelf?" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAccessibleDescription("Stories stay in your library.");
    // first focusable inside (the close button) has focus; background is inert
    expect(within(dialog).getByRole("button", { name: "Close" })).toHaveFocus();
    expect(opener.closest("[inert]")).not.toBeNull();
    // Tab cycles inside
    await user.tab();
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    await user.tab();
    expect(within(dialog).getByRole("button", { name: "Close" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(opener).toHaveFocus();
    expect(opener.closest("[inert]")).toBeNull();
    expect(document.body.style.overflow).toBe("");
  });
});

describe("Sheet", () => {
  it("closes on Escape and returns focus to the opener", async () => {
    function Harness() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <Button onClick={() => setOpen(true)}>Settings</Button>
          <Sheet open={open} onClose={() => setOpen(false)} title="Text settings">
            <button type="button">Bigger</button>
          </Sheet>
        </>
      );
    }
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "Settings" }));
    expect(screen.getByRole("dialog", { name: "Text settings" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("button", { name: "Settings" })).toHaveFocus();
  });
});

describe("Menu", () => {
  function Harness({ onRename }: { onRename: () => void }) {
    return (
      <Menu
        trigger={(props) => <button {...props}>Actions</button>}
        items={[
          { label: "Rename", onSelect: onRename },
          { label: "Duplicate", onSelect: () => undefined },
          { type: "separator" },
          { label: "Delete", onSelect: () => undefined },
        ]}
      />
    );
  }

  it("opens with ArrowDown, moves with arrows/Home/End/typeahead, Escape restores focus", async () => {
    const user = userEvent.setup();
    render(<Harness onRename={() => undefined} />);
    const trigger = screen.getByRole("button", { name: "Actions" });
    trigger.focus();
    await user.keyboard("{ArrowDown}");
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("menuitem", { name: "Rename" })).toHaveFocus();
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("menuitem", { name: "Duplicate" })).toHaveFocus();
    await user.keyboard("{End}");
    expect(screen.getByRole("menuitem", { name: "Delete" })).toHaveFocus();
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("menuitem", { name: "Rename" })).toHaveFocus();
    await user.keyboard("d");
    expect(screen.getByRole("menuitem", { name: "Duplicate" })).toHaveFocus();
    await user.keyboard("d");
    expect(screen.getByRole("menuitem", { name: "Delete" })).toHaveFocus();
    await user.keyboard("{Home}");
    expect(screen.getByRole("menuitem", { name: "Rename" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).toHaveFocus();
  });

  it("selects with Enter and closes", async () => {
    const onRename = vi.fn();
    const user = userEvent.setup();
    render(<Harness onRename={onRename} />);
    await user.click(screen.getByRole("button", { name: "Actions" }));
    await user.keyboard("{Enter}");
    expect(onRename).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Actions" })).toHaveAttribute("aria-expanded", "false");
  });
});

describe("Tabs", () => {
  it("activates automatically with arrow keys", async () => {
    function Harness() {
      const [v, setV] = useState<"a" | "b" | "c">("a");
      return (
        <Tabs
          label="Sections"
          value={v}
          onChange={setV}
          items={[
            { value: "a", label: "Overview", panel: <p>One</p> },
            { value: "b", label: "Chapters", panel: <p>Two</p> },
            { value: "c", label: "Notes", panel: <p>Three</p> },
          ]}
        />
      );
    }
    const user = userEvent.setup();
    render(<Harness />);
    await user.tab();
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveFocus();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Chapters" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel", { name: "Chapters" })).toHaveTextContent("Two");
    await user.keyboard("{ArrowLeft}{ArrowLeft}");
    expect(screen.getByRole("tab", { name: "Notes" })).toHaveFocus();
  });
});

describe("Cover, Progress, ListRow", () => {
  it("fallback hue is stable and the fallback is decorative by default", () => {
    expect(coverHueIndex("Worm")).toBe(coverHueIndex(" worm "));
    expect(coverHueIndex("Worm")).toBeGreaterThanOrEqual(1);
    expect(coverHueIndex("Worm")).toBeLessThanOrEqual(8);
    const { container } = render(<Cover title="Worm" />);
    expect(container.firstElementChild).toHaveAttribute("aria-hidden", "true");
    render(<Cover title="Pact" alt="Pact" />);
    expect(screen.getByRole("img", { name: "Pact" })).toBeInTheDocument();
  });

  it("falls back when the image fails", () => {
    const { container } = render(<Cover title="Twig" src="/broken.png" alt="Twig" />);
    const img = container.querySelector("img")!;
    act(() => {
      img.dispatchEvent(new Event("error"));
    });
    expect(screen.getByRole("img", { name: "Twig" }).tagName).toBe("DIV");
  });

  it("progress exposes value text", () => {
    render(<Progress label="Reading progress" value={41} max={98} valueText="Chapter 41 of 98" />);
    const bar = screen.getByRole("progressbar", { name: "Reading progress" });
    expect(bar).toHaveAttribute("aria-valuenow", "41");
    expect(bar).toHaveAttribute("aria-valuetext", "Chapter 41 of 98");
  });

  it("list row title is the link name; actions stay separate", () => {
    render(
      <MemoryRouter>
        <ListRow to="/s/1" title="Worm" meta="3 new" actions={<button type="button">Read</button>} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: "Worm" })).toHaveAttribute("href", "/s/1");
    expect(screen.getByRole("button", { name: "Read" })).toBeInTheDocument();
  });
});
