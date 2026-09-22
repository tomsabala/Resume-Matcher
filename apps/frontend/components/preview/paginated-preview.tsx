'use client';

import React, { useRef, useState, useCallback, useEffect } from 'react';
import { ZoomIn, ZoomOut, Eye, EyeOff, FileText } from 'lucide-react';
import { Button } from '@/components/ui/button';
import Resume from '@/components/dashboard/resume-component';
import type { ResumeDocument } from '@/lib/types/document';
import { type TemplateSettings } from '@/lib/types/template-settings';
import { PageContainer } from './page-container';
import { usePagination } from './use-pagination';
import { PAGE_DIMENSIONS, mmToPx, getContentAreaPx } from '@/lib/constants/page-dimensions';
import { useTranslations } from '@/lib/i18n';
import { useLanguage } from '@/lib/context/language-context';

interface PaginatedPreviewProps {
  doc: ResumeDocument;
  settings: TemplateSettings;
}

// A4 at 375px needs ~0.33, so the floor must sit below it or auto-fit cannot fit.
const MIN_ZOOM = 0.25;
const MAX_ZOOM = 1.5;
const ZOOM_STEP = 0.1;

/**
 * PaginatedPreview shows a WYSIWYG preview of the resume with actual page dimensions,
 * margin guides, and automatic pagination.
 */
export function PaginatedPreview({ doc, settings }: PaginatedPreviewProps) {
  const { t } = useTranslations();
  // Orders the CJK font fallback so the preview matches the generated PDF.
  const { contentLanguage } = useLanguage();
  const measurementRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [zoom, setZoom] = useState(0.6);
  const [showMargins, setShowMargins] = useState(false);
  const [autoZoom, setAutoZoom] = useState(true);
  const resumeSettings: TemplateSettings = {
    ...settings,
    margins: { top: 0, bottom: 0, left: 0, right: 0 },
  };

  const { pages, isCalculating } = usePagination({
    pageSize: settings.pageSize,
    margins: settings.margins,
    measurementRef,
  });

  // Calculate auto-zoom to fit container width
  const calculateAutoZoom = useCallback(() => {
    const container = containerRef.current;
    if (!container || !autoZoom) return;

    // Derive the padding from the element instead of hardcoding it — the scroll
    // container's padding is responsive (p-2 below sm, p-6 above).
    const style = getComputedStyle(container);
    const available =
      container.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
    // The preview pane is `display:none` on mobile until its tab is selected;
    // measuring then yields 0, and the observer below re-runs once it is shown.
    if (available <= 0) return;
    const pageWidthPx = mmToPx(PAGE_DIMENSIONS[settings.pageSize].width);
    const optimalZoom = Math.min(available / pageWidthPx, MAX_ZOOM);
    setZoom(Math.max(MIN_ZOOM, Math.min(optimalZoom, 0.75))); // Cap at 75% for usability
  }, [settings.pageSize, autoZoom]);

  // Auto-zoom on mount, on viewport resize, and when the pane itself is
  // resized — including 0 -> visible when the mobile pane switch reveals it.
  useEffect(() => {
    calculateAutoZoom();
    const handleResize = () => calculateAutoZoom();
    window.addEventListener('resize', handleResize);
    const container = containerRef.current;
    const observer =
      container && typeof ResizeObserver !== 'undefined'
        ? new ResizeObserver(handleResize)
        : undefined;
    observer?.observe(container!);
    return () => {
      window.removeEventListener('resize', handleResize);
      observer?.disconnect();
    };
  }, [calculateAutoZoom]);

  const handleZoomIn = () => {
    setAutoZoom(false);
    setZoom((z) => Math.min(z + ZOOM_STEP, MAX_ZOOM));
  };

  const handleZoomOut = () => {
    setAutoZoom(false);
    setZoom((z) => Math.max(z - ZOOM_STEP, MIN_ZOOM));
  };

  const toggleMargins = () => setShowMargins((s) => !s);

  // Get content area dimensions for the hidden measurement container
  const contentArea = getContentAreaPx(settings.pageSize, settings.margins);

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Controls bar */}
      <div className="flex flex-wrap items-center justify-between gap-2 px-2 py-2 border-b border-steel-grey bg-secondary shrink-0 sm:px-4">
        <div className="flex items-center gap-2">
          {/* Zoom controls */}
          <Button
            variant="ghost"
            size="icon"
            onClick={handleZoomOut}
            disabled={zoom <= MIN_ZOOM}
            className="h-8 w-8"
            aria-label={t('preview.zoomOut')}
            title={t('preview.zoomOut')}
          >
            <ZoomOut className="w-4 h-4" />
          </Button>
          <span className="font-mono text-xs w-12 text-center text-ink-soft">
            {Math.round(zoom * 100)}%
          </span>
          <Button
            variant="ghost"
            size="icon"
            onClick={handleZoomIn}
            disabled={zoom >= MAX_ZOOM}
            className="h-8 w-8"
            aria-label={t('preview.zoomIn')}
            title={t('preview.zoomIn')}
          >
            <ZoomIn className="w-4 h-4" />
          </Button>

          <div className="w-px h-5 bg-steel-grey mx-2" />

          {/* Margin toggle */}
          <Button
            variant={showMargins ? 'secondary' : 'ghost'}
            size="sm"
            onClick={toggleMargins}
            className="h-8 gap-1.5"
          >
            {showMargins ? <Eye className="w-4 h-4" /> : <EyeOff className="w-4 h-4" />}
            <span className="font-mono text-xs uppercase">{t('preview.margins')}</span>
          </Button>
        </div>

        {/* Page count */}
        <div className="flex items-center gap-2 text-ink-soft">
          <FileText className="w-4 h-4" />
          <span className="font-mono text-xs uppercase">
            {isCalculating
              ? t('preview.calculating')
              : pages.length === 1
                ? t('preview.pageCountSingular', { count: pages.length })
                : t('preview.pageCountPlural', { count: pages.length })}
          </span>
        </div>
      </div>

      {/* Scrollable preview area */}
      <div ref={containerRef} className="flex-1 overflow-auto bg-[#D5D5D0] p-2 sm:p-6">
        {/* Hidden measurement container - renders content at actual size */}
        <div
          ref={measurementRef}
          className="absolute opacity-0 pointer-events-none"
          style={{
            width: contentArea.width,
            left: -9999,
            top: 0,
          }}
          aria-hidden="true"
        >
          <Resume
            doc={doc}
            template={settings.template}
            settings={resumeSettings}
            locale={contentLanguage}
            translate={t}
            fallbackName={t('resume.defaults.name')}
          />
        </div>

        {/* Visible pages. `w-max min-w-full` centres a page narrower than the
            viewport but grows with a zoomed-in one, so an oversized page
            overflows to the right (scrollable) instead of to both sides. */}
        <div className="flex w-max min-w-full flex-col items-center gap-4">
          {pages.map((page, index) => (
            <React.Fragment key={page.pageNumber}>
              {index > 0 && (
                <div className="flex items-center gap-2 py-2">
                  <div className="h-px w-8 bg-steel-grey" />
                  <span className="font-mono text-[10px] text-steel-grey uppercase tracking-wider">
                    {t('preview.pageBreak')}
                  </span>
                  <div className="h-px w-8 bg-steel-grey" />
                </div>
              )}
              <PageContainer
                pageSize={settings.pageSize}
                margins={settings.margins}
                pageNumber={page.pageNumber}
                totalPages={pages.length}
                scale={zoom}
                showMarginGuides={showMargins}
                contentOffset={page.contentOffset}
                contentEnd={page.contentEnd}
              >
                <Resume
                  doc={doc}
                  template={settings.template}
                  settings={resumeSettings}
                  locale={contentLanguage}
                  translate={t}
                  fallbackName={t('resume.defaults.name')}
                />
              </PageContainer>
            </React.Fragment>
          ))}
        </div>
      </div>
    </div>
  );
}
