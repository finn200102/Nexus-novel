import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import SupportLinks from "./SupportLinks";
import { safeSupportLinks } from "../../lib/supportLinks";

describe("SupportLinks", () => {
  it("renders a labelled chip per platform that opens in a new tab", () => {
    render(
      <SupportLinks
        links={[
          { kind: "patreon", url: "https://www.patreon.com/writer" },
          { kind: "buymeacoffee", url: "https://buymeacoffee.com/writer" },
        ]}
      />,
    );

    expect(screen.getByRole("navigation", { name: "Support the author" })).toBeInTheDocument();
    const patreon = screen.getByRole("link", { name: /Patreon.*opens in a new tab/ });
    expect(patreon).toHaveAttribute("href", "https://www.patreon.com/writer");
    expect(patreon).toHaveAttribute("target", "_blank");
    expect(patreon).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getByRole("link", { name: /Buy Me a Coffee/ })).toBeInTheDocument();
  });

  it("renders nothing when there are no valid links", () => {
    const { container } = render(<SupportLinks links={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("drops links that are not https or not on a known platform", () => {
    const { container } = render(
      <SupportLinks
        links={[
          { kind: "patreon", url: "http://patreon.com/writer" },
          { kind: "kofi", url: "javascript:alert(1)" },
          { kind: "kofi", url: "https://phish.example.test/ko-fi.com" },
        ]}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

describe("safeSupportLinks", () => {
  it("accepts known hosts including www and subdomains, dedupes, and rejects unknown kinds", () => {
    expect(
      safeSupportLinks([
        { kind: "kofi", url: "https://ko-fi.com/a" },
        { kind: "kofi", url: "https://ko-fi.com/a" },
        { kind: "subscribestar", url: "https://www.subscribestar.adult/b" },
        { kind: "unknown", url: "https://liberapay.com/c" },
        null,
        "string",
      ]),
    ).toEqual([
      { kind: "kofi", url: "https://ko-fi.com/a" },
      { kind: "subscribestar", url: "https://www.subscribestar.adult/b" },
    ]);
  });

  it("returns an empty list for non-array input", () => {
    expect(safeSupportLinks(undefined)).toEqual([]);
    expect(safeSupportLinks({ kind: "kofi" })).toEqual([]);
  });
});
