import { useEffect, useState } from "react";
import apiClient from "../../services/apiClient";
import { onAccountStorageChange, storageGeneration } from "../../services/accountStorage";
import { coverHue } from "./coverFallback";
import { cx } from "./cx";

export type CoverSize = 48 | 72 | 112 | 160 | 180 | "fill";

export interface CoverProps {
  src?: string | null;
  title: string;
  author?: string | null;
  /** Width in px (height follows 2:3) or "fill" for the parent's width. Default 112. */
  size?: CoverSize;
  /**
   * Alt text. Default "" (decorative) because the title is normally shown next to the cover.
   * Pass the title when the cover stands alone.
   */
  alt?: string;
  className?: string;
  /** Eager-load above-the-fold covers. */
  priority?: boolean;
}

/** Fixed 2:3 cover with a generated fallback (hue from the title hash, title in serif). */
export function Cover({ src, title, author, size = 112, alt = "", className, priority }: CoverProps) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const [privateSrc, setPrivateSrc] = useState<string | null>(null);
  useEffect(() => {
    if (!src?.startsWith("nexus-cover:")) return;
    let active = true;
    let objectUrl: string | null = null;
    const generation = storageGeneration();
    const unsubscribe = onAccountStorageChange(() => { setPrivateSrc(null); if (objectUrl) URL.revokeObjectURL(objectUrl); });
    void apiClient.get(`/reader/covers/${src.split(":")[1]}`, { responseType: "blob" }).then((response) => {
      if (!active || generation !== storageGeneration()) return;
      objectUrl = URL.createObjectURL(response.data);
      setPrivateSrc(objectUrl);
    }).catch(() => { if (active) setFailedSrc(src); });
    return () => { active = false; unsubscribe(); if (objectUrl) URL.revokeObjectURL(objectUrl); setPrivateSrc(null); };
  }, [src]);
  const effectiveSrc = src?.startsWith("nexus-cover:") ? privateSrc : src;
  const showImage = Boolean(effectiveSrc) && failedSrc !== src;
  const style = size === "fill" ? undefined : { width: `${size}px` };
  const tiny = size === 48;
  const showAuthor = size === "fill" || size >= 112;

  if (showImage) {
    return (
      <img
        className={cx("ui-cover", className)}
        style={style}
        src={effectiveSrc ?? undefined}
        alt={alt}
        loading={priority ? "eager" : "lazy"}
        decoding="async"
        onError={() => setFailedSrc(src ?? null)}
      />
    );
  }
  const decorative = alt === "";
  return (
    <div
      className={cx("ui-cover", "ui-cover--fallback", tiny && "ui-cover--tiny", size === 72 && "ui-cover--small", className)}
      style={{ ...style, backgroundColor: coverHue(title) }}
      role={decorative ? undefined : "img"}
      aria-label={decorative ? undefined : alt}
      aria-hidden={decorative ? true : undefined}
    >
      {tiny ? <span className="ui-cover__initial">{title.trim().charAt(0)}</span> : <span className="ui-cover__title">{title}</span>}
      {author && showAuthor && <span className="ui-cover__author">{author}</span>}
    </div>
  );
}
