import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import SourceLinks from "./SourceLinks";

describe("SourceLinks", () => {
  it("renders external links that open in a new tab with safe rel", () => {
    render(<SourceLinks site="ao3" url="https://archiveofourown.org/works/9" />);

    const open = screen.getByRole("link", { name: /Open on Archive of Our Own/ });
    expect(open).toHaveAttribute("href", "https://archiveofourown.org/works/9");
    expect(open).toHaveAttribute("target", "_blank");
    expect(open).toHaveAttribute("rel", "noopener noreferrer");
    expect(open).toHaveTextContent("opens in a new tab");
    expect(screen.getByRole("link", { name: /Leave kudos on AO3/ })).toBeInTheDocument();
  });

  it("renders nothing for an unknown site", () => {
    const { container } = render(<SourceLinks site={null} url="https://x.test/a" />);
    expect(container).toBeEmptyDOMElement();
  });
});
