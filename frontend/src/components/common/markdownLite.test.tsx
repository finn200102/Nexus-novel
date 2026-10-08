import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MarkdownLite } from "./markdownLite";

describe("MarkdownLite", () => {
  it("renders the supported subset as elements", () => {
    const { container } = render(<MarkdownLite source={"**Bold** and *italic* with `code`\n- first\n- second"} />);

    expect(container.querySelector("strong")?.textContent).toBe("Bold");
    expect(container.querySelector("em")?.textContent).toBe("italic");
    expect(container.querySelector("code")?.textContent).toBe("code");
    expect(screen.getAllByRole("listitem").map((item) => item.textContent)).toEqual(["first", "second"]);
  });

  it("shows raw HTML as text and never creates elements from it", () => {
    const { container } = render(<MarkdownLite source={'<img src="x" onerror="alert(1)"> <script>boom</script>'} />);

    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(container.textContent).toContain('<img src="x" onerror="alert(1)">');
  });

  it("keeps line breaks inside a paragraph and splits paragraphs on blank lines", () => {
    const { container } = render(<MarkdownLite source={"one\ntwo\n\nthree"} />);

    expect(container.querySelectorAll("p")).toHaveLength(2);
    expect(container.querySelector("p br")).not.toBeNull();
  });
});
