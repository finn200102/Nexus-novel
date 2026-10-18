import { useId, useLayoutEffect, useRef, type KeyboardEvent, type ReactNode } from "react";
import { cx } from "./cx";

export interface TabItem<T extends string> {
  value: T;
  label: ReactNode;
  /** Panel content; omit when the tabs drive routes and the page renders the content. */
  panel?: ReactNode;
  disabled?: boolean;
}

export interface TabsProps<T extends string> {
  /** Accessible name of the tab list. */
  label: string;
  items: TabItem<T>[];
  value: T;
  onChange: (value: T) => void;
  /** Stick below the top bar while scrolling. */
  sticky?: boolean;
  className?: string;
}

/** APG tabs with automatic activation: arrows move and select, Home/End jump. */
export function Tabs<T extends string>({ label, items, value, onChange, sticky, className }: TabsProps<T>) {
  const base = useId();
  const refs = useRef(new Map<T, HTMLButtonElement>());
  const scroller = useRef<HTMLDivElement>(null);
  const enabled = items.filter((item) => !item.disabled);
  const hasPanels = items.some((item) => item.panel !== undefined);

  useLayoutEffect(() => {
    const container = scroller.current, selected = refs.current.get(value);
    if (!container || !selected) return;
    const reveal = () => {
      if (!container.clientWidth) return;
      const bounds = container.getBoundingClientRect(), tab = selected.getBoundingClientRect();
      // Keep labels clear of the edge fade. Move only this horizontal viewport;
      // scrollIntoView would also relocate the surrounding page and Reader.
      const gutter = Math.min(16, container.clientWidth / 4);
      const left = bounds.left + container.clientLeft + gutter;
      const right = bounds.left + container.clientLeft + container.clientWidth - gutter;
      const delta = tab.width > right - left || tab.left < left ? tab.left - left : tab.right > right ? tab.right - right : 0;
      if (!delta) return;
      const overflow = Math.max(0, container.scrollWidth - container.clientWidth);
      const rtl = window.getComputedStyle(container).direction === "rtl";
      container.scrollLeft = Math.max(rtl ? -overflow : 0, Math.min(rtl ? 0 : overflow, container.scrollLeft + delta));
    };
    reveal();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(reveal);
    observer?.observe(container); observer?.observe(selected);
    window.addEventListener("resize", reveal);
    document.fonts?.addEventListener("loadingdone", reveal);
    return () => { observer?.disconnect(); window.removeEventListener("resize", reveal); document.fonts?.removeEventListener("loadingdone", reveal); };
  }, [items, value]);

  const onKeyDown = (event: KeyboardEvent) => {
    if (!enabled.length) return;
    const index = enabled.findIndex((item) => item.value === value);
    let next: number | null = null;
    if (event.key === "ArrowRight") next = index < 0 ? 0 : (index + 1) % enabled.length;
    else if (event.key === "ArrowLeft") next = index < 0 ? enabled.length - 1 : (index - 1 + enabled.length) % enabled.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = enabled.length - 1;
    if (next === null) return;
    event.preventDefault();
    const target = enabled[next].value;
    onChange(target);
    refs.current.get(target)?.focus({ preventScroll: true });
  };

  return (
    <div className={cx("ui-tabs", className)}>
      <div ref={scroller} className={cx("ui-tabs__scroller", sticky && "ui-tabs__scroller--sticky")}>
        <div role="tablist" aria-label={label} className="ui-tabs__list" onKeyDown={onKeyDown}>
          {items.map((item) => {
            const selected = item.value === value;
            return (
              <button
                key={item.value}
                ref={(node) => {
                  if (node) refs.current.set(item.value, node);
                  else refs.current.delete(item.value);
                }}
                id={`${base}-tab-${item.value}`}
                type="button"
                role="tab"
                aria-selected={selected}
                aria-controls={item.panel !== undefined ? `${base}-panel-${item.value}` : undefined}
                tabIndex={selected ? 0 : -1}
                disabled={item.disabled}
                className="ui-tabs__tab"
                onClick={() => onChange(item.value)}
              >
                {item.label}
              </button>
            );
          })}
        </div>
      </div>
      {hasPanels &&
        items.map((item) =>
          item.panel === undefined ? null : (
            <div
              key={item.value}
              id={`${base}-panel-${item.value}`}
              role="tabpanel"
              aria-labelledby={`${base}-tab-${item.value}`}
              hidden={item.value !== value}
              tabIndex={0}
              className="ui-tabs__panel"
            >
              {item.value === value && item.panel}
            </div>
          ),
        )}
    </div>
  );
}
