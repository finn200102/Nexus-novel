import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Button, Field, FilterChip, IconButton, Input, InputChip, RadioCards, SegmentedControl, Select, Switch } from ".";

describe("Field", () => {
  it("wires label, hint and error to the control", () => {
    render(
      <Field label="Email" hint="We never share it." error="Enter an email.">
        {(props) => <input {...props} />}
      </Field>,
    );
    const input = screen.getByLabelText("Email");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription("We never share it. Enter an email.");
  });

  it("omits aria-invalid and describedby when there is nothing to describe", () => {
    render(<Field label="Name">{(props) => <input {...props} />}</Field>);
    const input = screen.getByLabelText("Name");
    expect(input).not.toHaveAttribute("aria-invalid");
    expect(input).not.toHaveAttribute("aria-describedby");
  });

  it("generates unique ids per field and honours a fixed id", () => {
    render(
      <>
        <Input label="First" />
        <Input label="Second" />
        <Input label="Third" id="third" />
      </>,
    );
    const first = screen.getByLabelText("First");
    const second = screen.getByLabelText("Second");
    expect(first.id).toBeTruthy();
    expect(first.id).not.toBe(second.id);
    expect(screen.getByLabelText("Third").id).toBe("third");
  });

  it("Select with label renders a labelled native select", () => {
    render(<Select label="Sort" options={[{ value: "a", label: "A" }]} error="Pick one." />);
    expect(screen.getByLabelText("Sort").tagName).toBe("SELECT");
    expect(screen.getByLabelText("Sort")).toHaveAccessibleDescription("Pick one.");
  });
});

describe("IconButton", () => {
  it("uses label as accessible name", () => {
    render(<IconButton label="Notifications" icon={<svg />} />);
    expect(screen.getByRole("button", { name: "Notifications" })).toBeInTheDocument();
  });

  it("refuses an empty label", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    expect(() => render(<IconButton label="  " icon={<svg />} />)).toThrow(/label/);
    spy.mockRestore();
  });

  it("exposes toggle state", () => {
    render(<IconButton label="Grid view" icon={<svg />} pressed />);
    expect(screen.getByRole("button", { name: "Grid view" })).toHaveAttribute("aria-pressed", "true");
  });
});

describe("Button", () => {
  it("defaults to type=button and blocks clicks while loading", async () => {
    const onClick = vi.fn();
    render(<Button loading onClick={onClick}>Save</Button>);
    const button = screen.getByRole("button", { name: "Save" });
    expect(button).toHaveAttribute("type", "button");
    expect(button).toHaveAttribute("aria-busy", "true");
    await userEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });
});

function Segmented() {
  const [value, setValue] = useState<"a" | "b" | "c">("a");
  return (
    <SegmentedControl
      label="Mode"
      value={value}
      onChange={setValue}
      options={[
        { value: "a", label: "Alpha" },
        { value: "b", label: "Beta", disabled: true },
        { value: "c", label: "Gamma" },
      ]}
    />
  );
}

describe("SegmentedControl / RadioCards", () => {
  it("is one tab stop and moves with arrow keys, skipping disabled options", async () => {
    const user = userEvent.setup();
    render(<Segmented />);
    await user.tab();
    expect(screen.getByRole("radio", { name: "Alpha" })).toHaveFocus();
    await user.keyboard("{ArrowRight}");
    const gamma = screen.getByRole("radio", { name: "Gamma" });
    expect(gamma).toHaveFocus();
    expect(gamma).toHaveAttribute("aria-checked", "true");
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("radio", { name: "Alpha" })).toHaveAttribute("aria-checked", "true");
    await user.keyboard("{End}");
    expect(gamma).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radiogroup", { name: "Mode" })).toBeInTheDocument();
  });

  it("RadioCards select with arrow keys", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <RadioCards
        label="Format"
        value="epub"
        onChange={onChange}
        options={[
          { value: "epub", label: "EPUB" },
          { value: "pdf", label: "PDF" },
        ]}
      />,
    );
    await user.tab();
    await user.keyboard("{ArrowDown}");
    expect(onChange).toHaveBeenCalledWith("pdf");
  });
});

describe("Switch and chips", () => {
  it("Switch toggles with Space", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<Switch label="Notifications" checked={false} onChange={onChange} />);
    const sw = screen.getByRole("switch", { name: "Notifications" });
    sw.focus();
    await user.keyboard(" ");
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it("FilterChip reports pressed state; InputChip has a named remove button", async () => {
    const onRemove = vi.fn();
    render(
      <>
        <FilterChip selected onChange={() => undefined}>Fantasy</FilterChip>
        <InputChip removeLabel="Remove tag Fantasy" onRemove={onRemove}>Fantasy</InputChip>
      </>,
    );
    expect(screen.getByRole("button", { name: "Fantasy" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(screen.getByRole("button", { name: "Remove tag Fantasy" }));
    expect(onRemove).toHaveBeenCalled();
  });

  it("search Input clears and refocuses", async () => {
    function Search() {
      const [v, setV] = useState("dragon");
      return <Input label="Search" search value={v} onChange={(e) => setV(e.target.value)} onClear={() => setV("")} />;
    }
    render(<Search />);
    await userEvent.click(screen.getByRole("button", { name: "Clear search" }));
    const box = screen.getByRole("searchbox", { name: "Search" });
    expect(box).toHaveValue("");
    expect(box).toHaveFocus();
  });
});
