import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ChapterSourceLink from "./ChapterSourceLink";

describe("ChapterSourceLink", () => {
  it("links the chapter on its source site in a new tab", () => {
    render(<ChapterSourceLink site="royalroad" href="https://www.royalroad.com/fiction/1/x/chapter/2" />);

    const link = screen.getByRole("link", { name: /Read this chapter on Royal Road/ });
    expect(link).toHaveAttribute("href", "https://www.royalroad.com/fiction/1/x/chapter/2");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(link).toHaveAttribute("target", "_blank");
  });

  it("renders nothing without a chapter URL", () => {
    const { container } = render(<ChapterSourceLink site="royalroad" href={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
