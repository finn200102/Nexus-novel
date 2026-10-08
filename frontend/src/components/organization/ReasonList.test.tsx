import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ReasonList } from "./ReasonList";

describe("ReasonList", () => {
  it("renders each reason as a list item", () => {
    render(<ReasonList reasons={["Similar to Source you rated 5★", "Shares tags: magic"]} />);

    expect(screen.getByLabelText("Why this")).toBeTruthy();
    expect(screen.getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "Similar to Source you rated 5★",
      "Shares tags: magic",
    ]);
  });

  it("renders nothing without reasons", () => {
    const { container } = render(<ReasonList reasons={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("supports the inline variant used inside card buttons", () => {
    const { container } = render(<ReasonList reasons={["Same author: Writer"]} inline />);
    expect(container.querySelector("ul")).toBeNull();
    expect(container.querySelector(".reason-list--inline")?.textContent).toBe("Same author: Writer");
  });
});
