import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { LEGACY_REDIRECTS, withSearch } from "./legacyRedirects";
import { LegacyRedirect } from "./LegacyRedirect";

const Probe = () => {
  const { pathname, search, hash } = useLocation();
  return <output data-testid="at">{pathname + search + hash}</output>;
};

const landAt = (url: string) => {
  render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        {LEGACY_REDIRECTS.map(({ from, to }) => (
          <Route key={from} path={from} element={<LegacyRedirect to={to} />} />
        ))}
        <Route path="*" element={<Probe />} />
      </Routes>
    </MemoryRouter>,
  );
  return screen.getByTestId("at").textContent;
};

describe("legacy redirects", () => {
  it.each([
    ["/discover/royalroad/42", "/story/42"],
    ["/discover/all/42?from=feed", "/story/42?from=feed"],
    ["/story-guide/9?through_chapter=12", "/story/9/guide?through_chapter=12"],
    ["/story-guide/9/review", "/story/9/guide/review"],
    ["/library/3", "/library?library=3"],
    ["/library/3?shelf=2", "/library?library=3&shelf=2"],
    ["/activity", "/updates"],
    ["/downloads", "/updates/downloads"],
    ["/account", "/settings/account"],
    ["/notifications", "/settings/notifications"],
    ["/hidden-content", "/settings/hidden"],
    ["/operations", "/admin/status"],
    ["/scrape-jobs", "/admin/jobs"],
    ["/integrations#webhooks", "/admin/duplicates#webhooks"],
  ])("%s → %s", (from, to) => {
    expect(landAt(from)).toBe(to);
  });

  it("leaves new and still-live routes alone", () => {
    for (const url of ["/", "/discover", "/discover/royalroad", "/library", "/library/3/novels/7", "/library/3/novels/7/12", "/admin/users", "/updates"]) {
      const { unmount } = render(<></>);
      unmount();
      expect(landAt(url)).toBe(url);
      document.body.innerHTML = "";
    }
  });

  it("joins queries", () => {
    expect(withSearch("/library?library=3", "?add=1")).toBe("/library?library=3&add=1");
    expect(withSearch("/updates", "")).toBe("/updates");
  });
});
