'use client';

import { useMemo } from 'react';
import type { ResumeDocument } from '@/lib/types/document';
import { visibleSections } from '@/lib/utils/section-helpers';
import { extractKeywords, calculateMatchStats } from '@/lib/utils/keyword-matcher';
import { JDDisplay } from './jd-display';
import { HighlightedResumeView } from './highlighted-resume-view';
import { CheckCircle, Target } from 'lucide-react';
import { useTranslations } from '@/lib/i18n';

interface JDComparisonViewProps {
  jobDescription: string;
  doc: ResumeDocument;
}

/**
 * Split view comparing job description with resume.
 * Left: JD (read-only)
 * Right: Resume with matching keywords highlighted
 */
export function JDComparisonView({ jobDescription, doc }: JDComparisonViewProps) {
  const { t } = useTranslations();

  // Extract keywords from JD
  const keywords = useMemo(() => extractKeywords(jobDescription), [jobDescription]);

  // Build full resume text for stats calculation. Every visible section
  // contributes, whatever its kind — the stats must describe the document the
  // user is actually sending.
  const resumeText = useMemo(() => {
    return visibleSections(doc)
      .flatMap((section) => [
        section.text,
        ...section.tags,
        ...section.groups.flatMap((group) => [group.label, ...group.values]),
        ...section.entries.flatMap((entry) => [
          entry.title,
          entry.subtitle,
          entry.meta,
          entry.summary,
          ...entry.bullets.map((bullet) => bullet.text),
        ]),
      ])
      .filter((part) => part.trim() !== '')
      .join(' ');
  }, [doc]);

  // Calculate match statistics
  const stats = useMemo(() => calculateMatchStats(resumeText, keywords), [resumeText, keywords]);

  return (
    <div className="h-full flex flex-col">
      {/* Stats Bar */}
      <div className="flex items-center justify-between px-4 py-3 bg-white border-b border-paper-tint">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <Target className="w-4 h-4 text-blue-600" />
            <span className="text-sm font-mono">
              {t('builder.jdMatch.stats.keywordsExtracted', { count: keywords.size })}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <CheckCircle className="w-4 h-4 text-green-600" />
            <span className="text-sm font-mono">
              {t('builder.jdMatch.stats.matchesFound', { count: stats.matchCount })}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-sm font-mono text-ink-soft">
            {t('builder.jdMatch.stats.matchRateLabel')}
          </span>
          <span
            className={`text-lg font-bold ${
              stats.matchPercentage >= 50
                ? 'text-green-600'
                : stats.matchPercentage >= 30
                  ? 'text-yellow-600'
                  : 'text-red-600'
            }`}
          >
            {stats.matchPercentage}%
          </span>
        </div>
      </div>

      {/* Split View */}
      <div className="flex-1 grid grid-cols-1 lg:grid-cols-2 min-h-0">
        {/* Left: JD */}
        <div className="border-r border-paper-tint overflow-hidden">
          <JDDisplay content={jobDescription} />
        </div>

        {/* Right: Resume with highlights */}
        <div className="overflow-hidden">
          <HighlightedResumeView doc={doc} keywords={keywords} />
        </div>
      </div>
    </div>
  );
}
