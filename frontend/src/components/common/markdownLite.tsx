import React from "react";

/**
 * A deliberately small Markdown subset: paragraphs, line breaks, **bold**,
 * *italic*, `code` and "- " bullet lists. Output is React elements built from
 * text nodes, so raw HTML in a note is shown as plain text, never injected.
 */

const INLINE = /(\*\*[^*\n]+\*\*|\*[^*\n]+\*|`[^`\n]+`)/g;

const renderInline = (text: string, keyPrefix: string): React.ReactNode[] =>
  text.split(INLINE).filter((part) => part !== "").map((part, index) => {
    const key = `${keyPrefix}-${index}`;
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      return <strong key={key}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
      return <code key={key}>{part.slice(1, -1)}</code>;
    }
    if (part.startsWith("*") && part.endsWith("*") && part.length > 2) {
      return <em key={key}>{part.slice(1, -1)}</em>;
    }
    return <React.Fragment key={key}>{part}</React.Fragment>;
  });

const renderMarkdownLite = (source: string): React.ReactNode[] => {
  const blocks: React.ReactNode[] = [];
  let paragraph: string[] = [];
  let list: string[] = [];

  const flushParagraph = () => {
    if (paragraph.length === 0) return;
    const key = `p-${blocks.length}`;
    blocks.push(
      <p key={key}>
        {paragraph.map((line, index) => (
          <React.Fragment key={`${key}-${index}`}>
            {index > 0 && <br />}
            {renderInline(line, `${key}-${index}`)}
          </React.Fragment>
        ))}
      </p>,
    );
    paragraph = [];
  };
  const flushList = () => {
    if (list.length === 0) return;
    const key = `ul-${blocks.length}`;
    blocks.push(
      <ul key={key}>
        {list.map((item, index) => <li key={`${key}-${index}`}>{renderInline(item, `${key}-${index}`)}</li>)}
      </ul>,
    );
    list = [];
  };

  for (const rawLine of source.replace(/\r\n?/g, "\n").split("\n")) {
    const bullet = rawLine.match(/^\s*[-*]\s+(.*)$/);
    if (bullet) {
      flushParagraph();
      list.push(bullet[1]);
    } else if (rawLine.trim() === "") {
      flushParagraph();
      flushList();
    } else {
      flushList();
      paragraph.push(rawLine.trim());
    }
  }
  flushParagraph();
  flushList();
  return blocks;
};

export const MarkdownLite: React.FC<{ source: string; className?: string }> = ({ source, className }) => (
  <div className={className ?? "markdown-lite"}>{renderMarkdownLite(source)}</div>
);
