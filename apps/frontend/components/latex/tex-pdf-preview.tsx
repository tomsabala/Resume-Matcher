'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Minus, Plus, Scan } from 'lucide-react';
import type * as PdfjsModule from 'pdfjs-dist';
import type { PDFDocumentLoadingTask, PDFDocumentProxy, RenderTask } from 'pdfjs-dist';
import { useDebouncedValue } from '@/hooks/use-debounced-value';
import { useTranslations } from '@/lib/i18n';
import {
  compileTexPdf,
  texFormatParams,
  TexCompileError,
  TexUnavailableError,
} from '@/lib/api/tex';
import type { TexFormatSettings, TexTemplateId } from '@/lib/api/tex';

interface TexPdfPreviewProps {
  resumeId: string;
  template: TexTemplateId;
  /** The formatting controls the engine reads: page size, margins, spacing
   * and font sizes. A recompile follows once they settle. */
  settings: TexFormatSettings;
  /** Bumped by the parent after a save or reset, so the compile reruns. */
  revision: number;
}

/**
 * Why a failure is stored rather than its message: translating inside the
 * effect would put `t` in its dependency list, and `t` is a fresh identity
 * every render — the preview would recompile in a loop.
 */
type Failure =
  | { kind: 'unavailable' }
  | { kind: 'compile'; message: string; log: string }
  | { kind: 'render' }
  | { kind: 'other'; message: string | null };

/** `'fit'` tracks the pane width; a number is an explicit zoom factor. */
type Zoom = 'fit' | number;

/** A parsed document and the loading task that owns its worker. */
type LoadedPdf = { doc: PDFDocumentProxy; task: PDFDocumentLoadingTask };

const ZOOM_STEP = 0.25;
const MIN_ZOOM = 0.25;
const MAX_ZOOM = 4;
/** Gap between stacked pages, and the breathing room around the stack. */
const PAGE_GAP = 16;

/**
 * pdf.js is ~400 KB and only the LaTeX surfaces need it, so it is imported on
 * first render rather than bundled into every route. The worker URL is
 * resolved through `import.meta.url` so the bundler emits it as an asset and
 * `basePath` is applied — a hardcoded `/pdf.worker.mjs` would 404 under the
 * `/a/resume-matcher` mount.
 *
 * The `legacy/` build, not the default one: pdf.js 6 calls
 * `Map.prototype.getOrInsertComputed`, which only the newest engines ship, so
 * the default build throws `TypeError: … is not a function` mid-render on
 * anything older. `legacy/` carries the core-js polyfills for exactly that
 * class of API and is byte-identical in rendering behaviour.
 */
let pdfjsPromise: Promise<typeof PdfjsModule> | null = null;
function loadPdfjs(): Promise<typeof PdfjsModule> {
  pdfjsPromise ??= import('pdfjs-dist/legacy/build/pdf.mjs').then((pdfjs) => {
    pdfjs.GlobalWorkerOptions.workerSrc = new URL(
      'pdfjs-dist/legacy/build/pdf.worker.min.mjs',
      import.meta.url
    ).toString();
    return pdfjs;
  });
  return pdfjsPromise;
}

/**
 * The engine-compiled PDF, shown beside its source.
 *
 * The LaTeX tab used to preview the browser-rendered HTML template, which is a
 * different renderer with different fonts and metrics: what the tab showed was
 * never what its Download PDF produced. This renders the same bytes the
 * download does, so the preview is the artifact.
 *
 * It draws them with pdf.js instead of handing a blob to `<object>`, because
 * the app is embedded in a `sandbox`ed iframe. Every sandboxed document has
 * the sandboxed-plugins flag set, with no token to clear it, so the built-in
 * PDF viewer never instantiates there: `<object>`, `<embed>` and a nested
 * `<iframe>` all paint nothing and report nothing. pdf.js is script and
 * canvas, which the sandbox permits, and is the same renderer Firefox's own
 * viewer uses — so fidelity is unchanged. Pages are rasterised at
 * `devicePixelRatio` so they stay sharp on HiDPI screens, and a transparent
 * text layer keeps the text selectable and searchable.
 */
export function TexPdfPreview({ resumeId, template, settings, revision }: TexPdfPreviewProps) {
  const { t } = useTranslations();
  const [loaded, setLoaded] = useState<LoadedPdf | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [compiling, setCompiling] = useState(true);
  const [zoom, setZoom] = useState<Zoom>('fit');
  const [fitScale, setFitScale] = useState(1);
  const [availableWidth, setAvailableWidth] = useState(0);

  const scrollRef = useRef<HTMLDivElement>(null);
  const pagesRef = useRef<HTMLDivElement>(null);
  // Cancelled before each re-render pass; a superseded raster would otherwise
  // paint stale pixels over the new scale.
  const tasksRef = useRef<RenderTask[]>([]);
  // Bumped per render pass; a pass that is no longer the newest abandons its
  // own work instead of publishing pages for a width or zoom already gone.
  const generationRef = useRef(0);

  // A compile is seconds of engine time, so the recompile follows the settled
  // controls; a slider drag would otherwise queue one compile per step.
  const formatKey = useMemo(() => texFormatParams(settings).toString(), [settings]);
  const debouncedKey = useDebouncedValue(formatKey, 500);
  // Synced in an effect declared before the compile one, so the compile reads
  // the latest settings while rerunning only on the debounced key.
  const settingsRef = useRef(settings);
  useEffect(() => {
    settingsRef.current = settings;
  });

  // Compile, then parse. The bytes are handed straight to pdf.js and never
  // become an object URL: nothing to revoke, so no window in which the view
  // points at a freed blob.
  useEffect(() => {
    let cancelled = false;
    let owned: PDFDocumentLoadingTask | null = null;

    setCompiling(true);
    setFailure(null);

    (async () => {
      const blob = await compileTexPdf(resumeId, template, settingsRef.current);
      const bytes = new Uint8Array(await blob.arrayBuffer());
      const pdfjs = await loadPdfjs();
      const task = pdfjs.getDocument({ data: bytes });
      owned = task;
      const doc = await task.promise;
      if (cancelled) return;
      // Handed to state, so the teardown effect below owns it from here.
      owned = null;
      setLoaded({ doc, task });
    })()
      .catch((error: unknown) => {
        if (cancelled) return;
        setLoaded(null);
        if (error instanceof TexCompileError) {
          setFailure({ kind: 'compile', message: error.message, log: error.log });
        } else if (error instanceof TexUnavailableError) {
          setFailure({ kind: 'unavailable' });
        } else if (error instanceof Error && error.name === 'InvalidPDFException') {
          setFailure({ kind: 'render' });
        } else {
          setFailure({
            kind: 'other',
            message: error instanceof Error ? error.message : null,
          });
        }
      })
      .finally(() => {
        if (!cancelled) setCompiling(false);
      });

    return () => {
      cancelled = true;
      // Only a document this run parsed but never published: the one in state
      // stays alive and on screen until its replacement is ready.
      void owned?.destroy();
    };
    // `revision` recompiles after a save or reset; `debouncedKey` after the
    // formatting controls settle.
  }, [resumeId, template, revision, debouncedKey]);

  // Tears down the previous document when a new one replaces it, and the last
  // one on unmount, so a closed tab leaves no worker parsing.
  useEffect(() => () => void loaded?.task.destroy(), [loaded]);

  // Fit tracks the pane, so the scale is a function of its width.
  useEffect(() => {
    const node = scrollRef.current;
    if (!node) return;
    const measure = () => setAvailableWidth(node.clientWidth - PAGE_GAP * 2);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  /**
   * One pass per (document, width, zoom). Passes overlap — a resize can land
   * mid-raster — so each takes a generation and abandons itself the moment a
   * newer one starts. Without it the late pass's `replaceChildren` could
   * publish stale pages over fresh ones.
   */
  const renderPages = useCallback(async (pdf: PDFDocumentProxy, width: number, requested: Zoom) => {
    const host = pagesRef.current;
    if (!host || width <= 0) return;

    const generation = (generationRef.current += 1);
    const current = () => generation === generationRef.current;
    tasksRef.current.forEach((task) => task.cancel());
    tasksRef.current = [];

    const { TextLayer } = await loadPdfjs();
    const outputScale = window.devicePixelRatio || 1;
    const first = await pdf.getPage(1);
    const natural = first.getViewport({ scale: 1 });
    const fit = width / natural.width;
    setFitScale(fit);
    const scale = requested === 'fit' ? fit : requested;

    const fragment = document.createDocumentFragment();

    for (let number = 1; number <= pdf.numPages; number += 1) {
      if (!current()) return;
      const page = number === 1 ? first : await pdf.getPage(number);
      const viewport = page.getViewport({ scale });

      const frame = document.createElement('div');
      frame.className = 'pdf-page';
      frame.style.width = `${Math.floor(viewport.width)}px`;
      frame.style.height = `${Math.floor(viewport.height)}px`;
      // The text layer positions its spans in unscaled PDF units and
      // multiplies by this, so it must match the raster scale exactly.
      frame.style.setProperty('--total-scale-factor', String(scale));

      const canvas = document.createElement('canvas');
      canvas.width = Math.floor(viewport.width * outputScale);
      canvas.height = Math.floor(viewport.height * outputScale);
      canvas.style.width = `${Math.floor(viewport.width)}px`;
      canvas.style.height = `${Math.floor(viewport.height)}px`;
      frame.appendChild(canvas);

      const textLayer = document.createElement('div');
      textLayer.className = 'pdf-text-layer';
      frame.appendChild(textLayer);

      fragment.appendChild(frame);

      const task = page.render({
        canvas,
        viewport,
        transform: outputScale === 1 ? undefined : [outputScale, 0, 0, outputScale, 0, 0],
      });
      // Tracked as it is created, so a pass that supersedes this one cancels
      // every raster already in flight rather than only the finished set.
      tasksRef.current.push(task);

      void task.promise
        .then(() => {
          if (!current()) return;
          return new TextLayer({
            textContentSource: page.streamTextContent(),
            container: textLayer,
            viewport,
          }).render();
        })
        .catch(() => {
          // A superseded raster takes its text layer with it; the next pass
          // rebuilds both. Selection is a convenience, never load-bearing.
        });
    }

    if (!current()) return;
    host.replaceChildren(fragment);
  }, []);

  useEffect(() => {
    const pdf = loaded?.doc;
    if (!pdf) return;
    void renderPages(pdf, availableWidth, zoom).catch(() => setFailure({ kind: 'render' }));
    // Read at cleanup time, not now: `renderPages` fills the ref as it goes.
    return () => tasksRef.current.forEach((task) => task.cancel());
  }, [loaded, availableWidth, zoom, renderPages]);

  const effectiveScale = zoom === 'fit' ? fitScale : zoom;
  // Functional, so two clicks in one frame are two steps: reading
  // `effectiveScale` from this render would make the second click a no-op.
  const changeZoom = (delta: number) =>
    setZoom((previous) => {
      const from = previous === 'fit' ? fitScale : previous;
      return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Number((from + delta).toFixed(2))));
    });

  if (failure) {
    return (
      <div className="border-2 border-alert-red bg-white p-3">
        <p className="font-mono text-xs text-alert-red">
          {failure.kind === 'unavailable'
            ? t('latex.noEngine')
            : failure.kind === 'render'
              ? t('latex.errors.render')
              : failure.message || t('latex.errors.compile')}
        </p>
        {failure.kind === 'compile' && failure.log && (
          <pre className="mt-2 max-h-96 overflow-auto bg-paper-tint p-2 font-mono text-[11px] whitespace-pre-wrap">
            {failure.log}
          </pre>
        )}
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center gap-2 border-b border-black bg-secondary px-3 py-2 font-mono text-xs uppercase text-steel-grey">
        {compiling || !loaded ? (
          <span>{t('latex.previewCompiling')}</span>
        ) : (
          <>
            <span>{t('latex.previewPages', { count: loaded.doc.numPages })}</span>
            <div className="ml-auto flex items-center gap-1">
              <button
                type="button"
                onClick={() => changeZoom(-ZOOM_STEP)}
                disabled={effectiveScale <= MIN_ZOOM}
                aria-label={t('latex.previewZoomOut')}
                title={t('latex.previewZoomOut')}
                className="flex h-7 w-7 items-center justify-center border border-black bg-white text-black hover:bg-paper-tint disabled:opacity-40"
              >
                <Minus className="h-3 w-3" />
              </button>
              <span className="w-12 text-center tabular-nums">
                {Math.round(effectiveScale * 100)}%
              </span>
              <button
                type="button"
                onClick={() => changeZoom(ZOOM_STEP)}
                disabled={effectiveScale >= MAX_ZOOM}
                aria-label={t('latex.previewZoomIn')}
                title={t('latex.previewZoomIn')}
                className="flex h-7 w-7 items-center justify-center border border-black bg-white text-black hover:bg-paper-tint disabled:opacity-40"
              >
                <Plus className="h-3 w-3" />
              </button>
              <button
                type="button"
                onClick={() => setZoom('fit')}
                aria-label={t('latex.previewFitWidth')}
                title={t('latex.previewFitWidth')}
                className={`flex h-7 w-7 items-center justify-center border border-black ${
                  zoom === 'fit' ? 'bg-black text-white' : 'bg-white text-black hover:bg-paper-tint'
                }`}
              >
                <Scan className="h-3 w-3" />
              </button>
            </div>
          </>
        )}
      </div>
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-auto bg-steel-grey/20">
        <div
          ref={pagesRef}
          role="group"
          aria-label={t('latex.previewLabel')}
          className="flex flex-col items-center gap-4 p-4"
        />
      </div>
    </div>
  );
}
