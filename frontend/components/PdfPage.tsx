"use client";

import { useEffect, useRef, useState } from "react";

interface Props {
  url: string;
  page: number;
  bbox: [number, number, number, number] | null;
}

interface Box {
  left: number;
  top: number;
  width: number;
  height: number;
}

interface Rendered {
  key: string;
  box: Box | null;
  height: number;
}

/**
 * One page of the cited document, with the highlighter drawn over the box the
 * passage came from. PDF.js is loaded on first use (it is large) and fetches
 * byte ranges, so a page deep in a long document costs the page, not the file.
 *
 * PyMuPDF's boxes are top-left-origin, y-down - the canvas's own convention -
 * so the highlight is a plain scale from PDF points to rendered pixels.
 */
// The legacy build carries its own polyfills: the modern one assumes Map
// methods that shipped in browsers only this year.
function pdfWorkerUrl(): string {
  return new URL("pdfjs-dist/legacy/build/pdf.worker.min.mjs", import.meta.url).toString();
}

export function PdfPage({ url, page, bbox }: Props) {
  const frame = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  // The page is rendered at the column's width, and again when that changes.
  const [width, setWidth] = useState(0);
  // Keyed by what was asked for, so a page still rendering never shows the
  // previous page's box.
  const key = `${url}#${page}@${width}`;
  const [rendered, setRendered] = useState<Rendered | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const status = failed === key ? "failed" : rendered?.key === key ? "ready" : "loading";
  const box = status === "ready" ? rendered?.box : null;
  const height = rendered?.key === key ? rendered.height : null;

  useEffect(() => {
    const element = frame.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.round(entry.contentRect.width)));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!width) return;
    let live = true;

    (async () => {
      const pdfjs = await import("pdfjs-dist/legacy/build/pdf.mjs");
      pdfjs.GlobalWorkerOptions.workerSrc = pdfWorkerUrl();
      const document = await pdfjs.getDocument({ url, disableAutoFetch: true }).promise;
      const pdfPage = await document.getPage(page);
      const target = canvas.current;
      if (!live || !target) return;

      const unscaled = pdfPage.getViewport({ scale: 1 });
      const scale = width / unscaled.width;
      const viewport = pdfPage.getViewport({ scale });
      const dpr = window.devicePixelRatio || 1;
      target.width = Math.floor(viewport.width * dpr);
      target.height = Math.floor(viewport.height * dpr);
      target.style.width = `${viewport.width}px`;
      target.style.height = `${viewport.height}px`;
      await pdfPage.render({ canvas: target, viewport, transform: [dpr, 0, 0, dpr, 0, 0] }).promise;
      if (!live) return;
      const [x0, y0, x1, y1] = bbox ?? [0, 0, 0, 0];
      setRendered({
        key,
        height: viewport.height,
        box: bbox
          ? { left: x0 * scale, top: y0 * scale, width: (x1 - x0) * scale, height: (y1 - y0) * scale }
          : null,
      });
    })().catch((error: unknown) => {
      console.error("page render failed", error);
      if (live) setFailed(key);
    });

    return () => {
      live = false;
    };
  }, [url, page, bbox, key, width]);

  if (status === "failed") return null;

  return (
    <div
      ref={frame}
      className="relative overflow-hidden border border-rule bg-white"
      style={height ? { height } : { aspectRatio: "1 / 1.414" }}
    >
      {status === "loading" && <div className="skeleton absolute inset-0" aria-hidden="true" />}
      <canvas ref={canvas} className="block" aria-label={`Page ${page}`} />
      {box && (
        <div
          aria-hidden="true"
          className="marker marker--sweep pointer-events-none absolute mix-blend-multiply"
          style={{
            left: box.left - 2,
            top: box.top - 2,
            width: box.width + 4,
            height: box.height + 4,
          }}
        />
      )}
    </div>
  );
}
