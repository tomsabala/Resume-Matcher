'use client';

import React from 'react';
import { type TemplateType } from '@/lib/types/template-settings';

/**
 * Template Thumbnail
 *
 * Visual representation of each template layout
 * Exported for use in FormattingControls
 */
interface TemplateThumbnailProps {
  type: TemplateType;
  isActive: boolean;
}

export const TemplateThumbnail: React.FC<TemplateThumbnailProps> = ({ type, isActive }) => {
  const lineColor = isActive ? 'bg-blue-700' : 'bg-steel-grey';
  const borderColor = isActive ? 'border-blue-700' : 'border-steel-grey';
  const accentColor = isActive ? 'bg-blue-600' : 'bg-blue-400';

  if (type === 'swiss-single') {
    // Single column thumbnail
    return (
      <div className={`w-14 h-18 border ${borderColor} bg-white p-1.5 flex flex-col gap-1`}>
        {/* Header */}
        <div className={`h-2 ${lineColor} w-full`}></div>
        <div className={`h-0.5 ${lineColor} w-3/4`}></div>
        {/* Sections */}
        <div className="flex-1 space-y-1 mt-1">
          <div className={`h-0.5 ${lineColor} w-full`}></div>
          <div className={`h-0.5 ${lineColor} w-5/6 opacity-50`}></div>
          <div className={`h-0.5 ${lineColor} w-4/6 opacity-50`}></div>
          <div className="h-1"></div>
          <div className={`h-0.5 ${lineColor} w-full`}></div>
          <div className={`h-0.5 ${lineColor} w-5/6 opacity-50`}></div>
          <div className={`h-0.5 ${lineColor} w-3/6 opacity-50`}></div>
        </div>
      </div>
    );
  }

  // Serif, ruled-heading single column: the browser-rendered Academic Serif
  // and both engine-compiled LaTeX templates share this silhouette.
  if (type === 'latex' || type === 'tex-classic' || type === 'tex-compact') {
    // LaTeX thumbnail - centered name + Title-Case ruled section headers (serif feel)
    return (
      <div className={`w-14 h-18 border ${borderColor} bg-white p-1.5 flex flex-col gap-1`}>
        {/* Centered name + contact */}
        <div className="flex flex-col items-center gap-0.5">
          <div className={`h-1.5 ${lineColor} w-2/3`}></div>
          <div className={`h-0.5 ${lineColor} w-1/2 opacity-60`}></div>
        </div>
        {/* Sections: each header is a full-width line with a bottom rule */}
        <div className="flex-1 space-y-1 mt-1">
          <div className={`h-0.5 ${lineColor} w-2/5 border-b ${borderColor} pb-1`}></div>
          <div className={`h-0.5 ${lineColor} w-5/6 opacity-50`}></div>
          <div className={`h-0.5 ${lineColor} w-4/6 opacity-50`}></div>
          <div className="h-0.5"></div>
          <div className={`h-0.5 ${lineColor} w-1/3 border-b ${borderColor} pb-1`}></div>
          <div className={`h-0.5 ${lineColor} w-5/6 opacity-50`}></div>
        </div>
      </div>
    );
  }

  if (type === 'clean') {
    // Clean thumbnail - centered light name + large understated gray uppercase headers
    return (
      <div className={`w-14 h-18 border ${borderColor} bg-white p-1.5 flex flex-col gap-1`}>
        {/* Centered light name + contact line */}
        <div className="flex flex-col items-center gap-0.5">
          <div className={`h-1.5 ${lineColor} w-1/2 opacity-70`}></div>
          <div className={`h-0.5 ${lineColor} w-2/3 opacity-40`}></div>
        </div>
        {/* Large gray section headers (taller, lower opacity) + thin rule */}
        <div className="flex-1 space-y-1 mt-1">
          <div className={`h-1 ${lineColor} w-1/2 opacity-30 border-b ${borderColor}`}></div>
          <div className={`h-0.5 ${lineColor} w-5/6 opacity-50`}></div>
          <div className={`h-0.5 ${lineColor} w-4/6 opacity-50`}></div>
          <div className="h-0.5"></div>
          <div className={`h-1 ${lineColor} w-2/5 opacity-30 border-b ${borderColor}`}></div>
          <div className={`h-0.5 ${lineColor} w-5/6 opacity-50`}></div>
        </div>
      </div>
    );
  }

  if (type === 'modern') {
    // Modern template thumbnail - with accent color highlights
    return (
      <div className={`w-14 h-18 border ${borderColor} bg-white p-1.5 flex flex-col gap-1`}>
        {/* Header with accent underline */}
        <div className="flex flex-col items-center gap-0.5">
          <div className={`h-2 ${lineColor} w-3/4`}></div>
          <div className={`h-0.5 ${accentColor} w-1/3`}></div>
        </div>
        {/* Sections with accent headers */}
        <div className="flex-1 space-y-1 mt-1">
          <div className={`h-0.5 ${accentColor} w-full`}></div>
          <div className={`h-0.5 ${lineColor} w-5/6 opacity-50`}></div>
          <div className={`h-0.5 ${lineColor} w-4/6 opacity-50`}></div>
          <div className="h-0.5"></div>
          <div className={`h-0.5 ${accentColor} w-full`}></div>
          <div className={`h-0.5 ${lineColor} w-5/6 opacity-50`}></div>
          <div className={`h-0.5 ${lineColor} w-3/6 opacity-50`}></div>
        </div>
      </div>
    );
  }

  if (type === 'modern-two-column') {
    // Modern two-column template thumbnail - accent colors + two columns
    return (
      <div className={`w-14 h-18 border ${borderColor} bg-white p-1.5 flex flex-col gap-1`}>
        {/* Header with accent underline */}
        <div className="flex flex-col items-center gap-0.5">
          <div className={`h-1.5 ${lineColor} w-3/4`}></div>
          <div className={`h-0.5 ${accentColor} w-1/3`}></div>
        </div>
        {/* Two columns */}
        <div className="flex-1 flex gap-1 mt-1">
          {/* Left column (wider) - with accent headers */}
          <div className="w-2/3 space-y-0.5">
            <div className={`h-0.5 ${accentColor} w-full`}></div>
            <div className={`h-0.5 ${lineColor} w-5/6 opacity-50`}></div>
            <div className={`h-0.5 ${lineColor} w-4/6 opacity-50`}></div>
            <div className="h-0.5"></div>
            <div className={`h-0.5 ${accentColor} w-full`}></div>
            <div className={`h-0.5 ${lineColor} w-5/6 opacity-50`}></div>
          </div>
          {/* Right column (narrower). Active state uses a heavier full
              border instead of a left stripe (impeccable BAN 1). */}
          <div
            className={`w-1/3 border ${isActive ? 'border-blue-600' : 'border-blue-300'} pl-1 space-y-0.5`}
          >
            <div className={`h-0.5 ${accentColor} w-full`}></div>
            <div className={`h-0.5 ${lineColor} w-4/5 opacity-50`}></div>
            <div className="h-0.5"></div>
            <div className={`h-0.5 ${accentColor} w-full`}></div>
            <div className={`h-0.5 ${lineColor} w-3/5 opacity-50`}></div>
          </div>
        </div>
      </div>
    );
  }

  if (type === 'vivid') {
    // Vivid thumbnail - two-tone accent name + accent headers + accent arrow bullets
    return (
      <div className={`w-14 h-18 border ${borderColor} bg-white p-1.5 flex flex-col gap-1`}>
        {/* Two-tone name (left-aligned) */}
        <div className="flex items-center gap-0.5">
          <div className={`h-1.5 ${accentColor} w-1/3`}></div>
          <div className={`h-1.5 ${accentColor} w-1/4 opacity-50`}></div>
        </div>
        <div className={`h-0.5 ${lineColor} w-2/3 opacity-40`}></div>
        {/* Two columns (no divider) */}
        <div className="flex-1 flex gap-1 mt-0.5">
          {/* Left column with arrow ticks */}
          <div className="w-2/3 space-y-0.5">
            <div className={`h-0.5 ${accentColor} w-1/2`}></div>
            <div className="flex items-center gap-0.5">
              <div className={`h-0.5 w-0.5 ${accentColor}`}></div>
              <div className={`h-0.5 ${lineColor} w-5/6 opacity-50`}></div>
            </div>
            <div className="flex items-center gap-0.5">
              <div className={`h-0.5 w-0.5 ${accentColor}`}></div>
              <div className={`h-0.5 ${lineColor} w-4/6 opacity-50`}></div>
            </div>
            <div className="h-0.5"></div>
            <div className={`h-0.5 ${accentColor} w-2/5`}></div>
          </div>
          {/* Right column (sidebar) */}
          <div className="w-1/3 space-y-0.5">
            <div className={`h-0.5 ${accentColor} w-full`}></div>
            <div className={`h-0.5 ${lineColor} w-4/5 opacity-50`}></div>
            <div className="h-0.5"></div>
            <div className={`h-0.5 ${accentColor} w-full`}></div>
            <div className={`h-0.5 ${lineColor} w-3/5 opacity-50`}></div>
          </div>
        </div>
      </div>
    );
  }

  // Two column thumbnail (swiss-two-column)
  return (
    <div className={`w-14 h-18 border ${borderColor} bg-white p-1.5 flex flex-col gap-1`}>
      {/* Header - centered */}
      <div className="flex flex-col items-center gap-0.5">
        <div className={`h-1.5 ${lineColor} w-3/4`}></div>
        <div className={`h-0.5 ${lineColor} w-1/2 opacity-70`}></div>
      </div>
      {/* Two columns */}
      <div className="flex-1 flex gap-1 mt-1">
        {/* Left column (wider) */}
        <div className="w-2/3 space-y-0.5">
          <div className={`h-0.5 ${lineColor} w-full`}></div>
          <div className={`h-0.5 ${lineColor} w-5/6 opacity-50`}></div>
          <div className={`h-0.5 ${lineColor} w-4/6 opacity-50`}></div>
          <div className="h-0.5"></div>
          <div className={`h-0.5 ${lineColor} w-full`}></div>
          <div className={`h-0.5 ${lineColor} w-5/6 opacity-50`}></div>
        </div>
        {/* Right column (narrower) */}
        <div className="w-1/3 border-l border-paper-tint pl-1 space-y-0.5">
          <div className={`h-0.5 ${lineColor} w-full`}></div>
          <div className={`h-0.5 ${lineColor} w-4/5 opacity-50`}></div>
          <div className="h-0.5"></div>
          <div className={`h-0.5 ${lineColor} w-full`}></div>
          <div className={`h-0.5 ${lineColor} w-3/5 opacity-50`}></div>
        </div>
      </div>
    </div>
  );
};
