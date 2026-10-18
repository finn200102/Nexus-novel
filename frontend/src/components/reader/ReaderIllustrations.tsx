import { useEffect, useRef, useState, type ReactNode } from "react";
import { Dialog } from "../ui/Dialog";
import { Button } from "../ui/Button";

type Illustration = { src: string; description: string };
// Chapter sanitization permits embedded raster images. Viewing never follows an
// arbitrary remote URL or changes the source markup used by reading locators.
const embeddedRaster = /^data:image\/(?:png|jpeg|webp|gif);base64,[A-Za-z0-9+/=]+$/;

export function ReaderIllustrations({ children }: { children: ReactNode }) {
  const body = useRef<HTMLDivElement>(null);
  const [gallery, setGallery] = useState<Illustration[]>([]);
  const [index, setIndex] = useState(0);
  const [zoom, setZoom] = useState(1);
  const [failed, setFailed] = useState(false);
  const viewport = useRef<HTMLDivElement>(null);
  const images = () => Array.from(body.current?.querySelectorAll<HTMLImageElement>("img") ?? [])
    .filter(image => !image.closest("a") && embeddedRaster.test(image.getAttribute("src") ?? ""));
  useEffect(() => {
    for (const image of images()) {
      image.tabIndex = 0;
      image.setAttribute("role", "button");
      image.setAttribute("aria-label", `Open illustration: ${image.alt.trim() || "Chapter image"}`);
    }
  }, [children]);
  const open = (image: HTMLImageElement) => {
    const available = images(), selected = available.indexOf(image);
    if (selected < 0) return false;
    // Pointer activation does not focus images by default. Remember this image
    // through the shared dialog's focus restoration without scrolling the story.
    image.focus({ preventScroll: true });
    setGallery(available.map(item => ({ src: item.getAttribute("src")!, description: item.alt.trim() || "Chapter image" })));
    setIndex(selected); setZoom(1); setFailed(false);
    return true;
  };
  const navigate = (next: number) => {
    if (next < 0 || next >= gallery.length) return;
    setIndex(next); setZoom(1); setFailed(false);
    viewport.current?.scrollTo?.({ top: 0, left: 0 });
  };
  useEffect(() => {
    if (!gallery.length) return;
    const keys = (event: KeyboardEvent) => {
      const layers = document.querySelectorAll(".ui-modal-layer");
      if (!layers[layers.length - 1]?.contains(viewport.current)) return;
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      event.preventDefault(); event.stopPropagation();
      const next = index + (event.key === "ArrowRight" ? 1 : -1);
      if (next < 0 || next >= gallery.length) return;
      setIndex(next); setZoom(1); setFailed(false);
      viewport.current?.scrollTo?.({ top: 0, left: 0 });
    };
    // Safari can return focus to body after clicking a button. Capture gallery
    // keys while this is the top dialog, before background reader shortcuts.
    document.addEventListener("keydown", keys, true);
    return () => document.removeEventListener("keydown", keys, true);
  }, [gallery.length, index]);
  const selected = gallery[index];
  return <div ref={body} className="reader-illustrations" onClick={event => {
    if (event.target instanceof HTMLImageElement && open(event.target)) {
      event.preventDefault(); event.stopPropagation();
    }
  }} onKeyDown={event => {
    if ((event.key === "Enter" || event.key === " ") && event.target instanceof HTMLImageElement && open(event.target)) {
      event.preventDefault(); event.stopPropagation();
    }
  }}>
    {children}
    <div onClick={event => event.stopPropagation()} onKeyDown={event => {
      if (!gallery.length) return;
      if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault(); event.stopPropagation(); navigate(index + (event.key === "ArrowRight" ? 1 : -1));
      }
    }}>
      <Dialog open={!!selected} onClose={() => setGallery([])} title="Chapter illustration" className="reader-image-dialog" closeLabel="Close illustration">
        {selected && <>
          <p aria-live="polite">{index + 1} of {gallery.length} · {selected.description}</p>
          <div className="reader-image-controls">
            <Button size="sm" disabled={index === 0} onClick={() => navigate(index - 1)}>Previous image</Button>
            <Button size="sm" disabled={index === gallery.length - 1} onClick={() => navigate(index + 1)}>Next image</Button>
            <Button size="sm" disabled={zoom === 1} onClick={() => setZoom(value => Math.max(1, value - 0.5))} aria-label="Zoom out">−</Button>
            <Button size="sm" disabled={zoom === 3} onClick={() => setZoom(value => Math.min(3, value + 0.5))} aria-label="Zoom in">+</Button>
            <Button size="sm" onClick={() => { setZoom(1); viewport.current?.scrollTo?.({ top: 0, left: 0 }); }}>Fit image</Button>
            <span aria-live="polite">{Math.round(zoom * 100)}%</span>
          </div>
          <div ref={viewport} className="reader-image-viewport" tabIndex={0} aria-label="Illustration; scroll to explore when zoomed">
            {failed ? <p role="status">This image could not be displayed.</p> : <img key={index} src={selected.src} alt={selected.description} style={{ width: `${zoom * 100}%`, maxHeight: zoom === 1 ? "65dvh" : undefined, objectFit: "contain" }} onError={() => setFailed(true)} />}
          </div>
        </>}
      </Dialog>
    </div>
  </div>;
}
