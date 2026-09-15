'use client';

import { useMemo } from 'react';
import type { ResumeDocument, Section } from '@/lib/types/document';
import { segmentTextByKeywords } from '@/lib/utils/keyword-matcher';
import { sectionHeading, visibleSections } from '@/lib/utils/section-helpers';
import { FileUser } from 'lucide-react';
import { useTranslations } from '@/lib/i18n';
import { cn } from '@/lib/utils';

interface HighlightedResumeViewProps {
  doc: ResumeDocument;
  keywords: Set<string>;
}

/**
 * Display resume content with matching keywords highlighted.
 *
 * Every visible section is covered, whatever the user called it — the previous
 * version enumerated the six built-ins, so a user-authored section was
 * silently excluded from the JD match view.
 */
export function HighlightedResumeView({ doc, keywords }: HighlightedResumeViewProps) {
  const { t } = useTranslations();
  const sections = visibleSections(doc);

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center gap-2 p-4 border-b border-paper-tint bg-paper-tint">
        <FileUser className="w-4 h-4 text-ink-soft" />
        <h3 className="font-mono text-sm font-bold uppercase text-ink-soft">
          {t('builder.jdMatch.yourResume')}
        </h3>
        <span className="text-xs text-steel-grey ml-2">
          {t('builder.jdMatch.matchingKeywordsHighlighted')}
        </span>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-6">
        {sections.map((section) => (
          <SectionPanel key={section.id} title={sectionHeading(section, t)}>
            <SectionBody section={section} keywords={keywords} />
          </SectionPanel>
        ))}
      </div>
    </div>
  );
}

/** Renders whichever field group the section's kind selects. */
function SectionBody({ section, keywords }: { section: Section; keywords: Set<string> }) {
  const { t } = useTranslations();

  if (section.kind === 'text') {
    return <HighlightedText text={section.text} keywords={keywords} />;
  }

  if (section.kind === 'tags') {
    return (
      <div className="flex flex-wrap gap-1">
        {section.tags.map((tag, i) => (
          <SkillTag key={i} text={tag} keywords={keywords} />
        ))}
      </div>
    );
  }

  if (section.kind === 'groups') {
    return (
      <>
        {section.groups.map((group, i) => (
          <div key={i} className="mb-3 last:mb-0">
            {group.label && (
              <div className="text-xs font-mono uppercase text-steel-grey mb-1">{group.label}</div>
            )}
            <div className="flex flex-wrap gap-1">
              {group.values.map((value, valueIndex) => (
                <SkillTag key={valueIndex} text={value} keywords={keywords} />
              ))}
            </div>
          </div>
        ))}
      </>
    );
  }

  return (
    <>
      {section.entries.map((entry) => (
        <div key={entry.id} className="mb-4 last:mb-0">
          <div className="font-semibold text-ink-soft">
            <HighlightedText text={entry.title} keywords={keywords} />
            {entry.subtitle && (
              <span className="text-ink-soft">
                {t('builder.jdMatch.atSeparator')}
                <HighlightedText text={entry.subtitle} keywords={keywords} />
              </span>
            )}
          </div>
          {entry.period && <div className="text-xs text-steel-grey mb-1">{entry.period}</div>}
          {entry.summary && (
            <div className="text-sm text-ink-soft mb-1">
              <HighlightedText text={entry.summary} keywords={keywords} />
            </div>
          )}
          {entry.bullets.length > 0 && (
            <ul className="space-y-1 text-sm">
              {entry.bullets.map((bullet, i) => {
                // Honour the per-row bullet/plain setting so this preview
                // agrees with the resume preview and the PDF.
                const showMarker = bullet.style !== 'plain';
                return (
                  <li key={i} className={cn('flex text-ink-soft', showMarker && 'ml-4')}>
                    {showMarker && (
                      <span className="mr-1.5 flex-shrink-0" aria-hidden="true">
                        &bull;&nbsp;
                      </span>
                    )}
                    <span>
                      <HighlightedText text={bullet.text} keywords={keywords} />
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      ))}
    </>
  );
}

/**
 * Section wrapper component
 */
function SectionPanel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border border-paper-tint bg-white rounded-none">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-paper-tint bg-paper-tint">
        <span className="font-mono text-xs font-bold uppercase text-ink-soft">{title}</span>
      </div>
      <div className="p-3">{children}</div>
    </div>
  );
}

/**
 * Component to render text with highlighted keywords.
 */
function HighlightedText({ text, keywords }: { text: string; keywords: Set<string> }) {
  const segments = useMemo(() => segmentTextByKeywords(text, keywords), [text, keywords]);

  return (
    <span>
      {segments.map((segment, i) =>
        segment.isMatch ? (
          <mark key={i} className="bg-yellow-200 text-black px-0.5">
            {segment.text}
          </mark>
        ) : (
          <span key={i}>{segment.text}</span>
        )
      )}
    </span>
  );
}

/**
 * Skill tag with optional highlighting
 */
function SkillTag({ text, keywords }: { text: string; keywords: Set<string> }) {
  const isMatch = keywords.has(text.toLowerCase());

  return (
    <span
      className={`inline-block px-2 py-0.5 text-xs ${
        isMatch ? 'bg-yellow-200 text-black font-medium' : 'bg-background text-ink-soft'
      }`}
    >
      {text}
    </span>
  );
}
