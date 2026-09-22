'use client';

import React from 'react';
import Resume from '@/components/dashboard/resume-component';
import type { ResumeDocument } from '@/lib/types/document';
import { type TemplateSettings } from '@/lib/types/template-settings';
import { useTranslations } from '@/lib/i18n';
import { useLanguage } from '@/lib/context/language-context';

export interface ReadingPreviewProps {
  doc: ResumeDocument;
  settings: TemplateSettings;
}

/**
 * The reflowed reading view — the phone default, with `PaginatedPreview`'s
 * scaled A4 one tap away.
 *
 * `resume-print` is load-bearing: the already-built mobile CSS scoped to
 * `:global(.resume-print)` inside `@media screen and (max-width: 639px)` drops
 * `.resume-body` padding from 10mm to 1rem and collapses two-column templates
 * to one. `settings` is passed **unmodified** — unlike `PaginatedPreview`,
 * which zeroes the margins because `PageContainer` supplies them, this view has
 * no page container and the screen override handles the phone case.
 */
export function ReadingPreview({ doc, settings }: ReadingPreviewProps) {
  const { t } = useTranslations();
  // Orders the CJK font fallback so the reading view matches the generated PDF.
  const { contentLanguage } = useLanguage();

  return (
    <div className="flex-1 overflow-y-auto bg-[#D5D5D0] p-2 sm:p-6">
      <div className="resume-print mx-auto w-full max-w-[210mm] border-2 border-black bg-white shadow-sw-card">
        <Resume
          doc={doc}
          template={settings.template}
          settings={settings}
          locale={contentLanguage}
          translate={t}
          fallbackName={t('resume.defaults.name')}
        />
      </div>
    </div>
  );
}
