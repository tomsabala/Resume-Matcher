'use client';

import type { ResumeDocument, Section } from '@/lib/types/document';
import { sectionHeading, visibleSections } from '@/lib/utils/section-helpers';
import { useTranslations } from '@/lib/i18n';

interface LivePreviewProps {
  doc: ResumeDocument;
  inferredSkills: string[];
}

function dedupeSkills(skills: string[]): string[] {
  const seen = new Set<string>();
  const unique: string[] = [];
  for (const skill of skills) {
    const trimmed = skill.trim();
    // Locale-invariant casing (matches the backend's casefold) — toLocaleLowerCase
    // would diverge in some locales (e.g. Turkish dotted/dotless I).
    const key = trimmed.toLowerCase();
    if (!trimmed || seen.has(key)) continue;
    seen.add(key);
    unique.push(trimmed);
  }
  return unique;
}

/** Every short value already written into the document, for dedupe against suggestions. */
function writtenValues(sections: Section[]): Set<string> {
  const values = new Set<string>();
  for (const section of sections) {
    for (const tag of section.tags) values.add(tag.trim().toLowerCase());
    for (const group of section.groups) {
      for (const value of group.values) values.add(value.trim().toLowerCase());
    }
  }
  return values;
}

export function LivePreview({ doc, inferredSkills }: LivePreviewProps) {
  const { t } = useTranslations();
  const sections = visibleSections(doc);
  const alreadyWritten = writtenValues(sections);
  // Only surface a suggestion the document does not already carry; the rest are
  // rendered by their own section below.
  const suggestedSkills = dedupeSkills(inferredSkills).filter(
    (skill) => !alreadyWritten.has(skill.toLowerCase())
  );

  const hasAnyContent =
    Boolean(doc.header.name.trim()) || sections.length > 0 || suggestedSkills.length > 0;

  return (
    <aside
      aria-label={t('resumeWizard.preview.label')}
      className="border-2 border-black bg-white p-5 shadow-[4px_4px_0px_0px_#000000]"
    >
      <p className="font-mono text-xs font-bold uppercase tracking-wider text-blue-700">
        {t('resumeWizard.preview.label')}
      </p>

      {!hasAnyContent ? (
        <p className="mt-6 font-sans text-sm text-steel-grey">{t('resumeWizard.preview.empty')}</p>
      ) : (
        <div className="mt-3 space-y-5">
          <div>
            <h2 className="font-serif text-2xl font-bold leading-tight">
              {doc.header.name.trim() || t('resumeWizard.preview.unnamed')}
            </h2>
            {doc.header.headline.trim() && (
              <p className="font-sans text-sm text-steel-grey">{doc.header.headline}</p>
            )}
          </div>

          {sections.map((section) => (
            <section key={section.id}>
              <p className="border-b border-black pb-1 font-mono text-xs font-bold uppercase tracking-wider">
                {sectionHeading(section, t)}
              </p>
              <SectionSummary section={section} />
            </section>
          ))}

          {suggestedSkills.length > 0 && (
            <section>
              <p className="border-b border-black pb-1 font-mono text-xs font-bold uppercase tracking-wider">
                {t('resumeWizard.preview.skills')}
              </p>
              <div className="mt-2 flex flex-wrap gap-2">
                {suggestedSkills.map((skill) => (
                  <span
                    key={skill}
                    className="border border-green-700 bg-background px-2 py-1 font-mono text-xs text-green-700"
                  >
                    {skill}
                    <span aria-hidden="true"> ✓</span>
                  </span>
                ))}
              </div>
            </section>
          )}
        </div>
      )}
    </aside>
  );
}

/** Compact rendering of whichever field group the section's kind selects. */
function SectionSummary({ section }: { section: Section }) {
  if (section.kind === 'text') {
    return <p className="mt-2 font-sans text-xs leading-snug">{section.text}</p>;
  }

  if (section.kind === 'tags') {
    return (
      <div className="mt-2 flex flex-wrap gap-2">
        {section.tags.map((tag) => (
          <span key={tag} className="border border-black bg-background px-2 py-1 font-mono text-xs">
            {tag}
          </span>
        ))}
      </div>
    );
  }

  if (section.kind === 'groups') {
    return (
      <div className="mt-2 space-y-2">
        {section.groups.map((group, index) => (
          <div key={index}>
            {group.label && (
              <p className="font-mono text-xs uppercase text-steel-grey">{group.label}</p>
            )}
            <div className="mt-1 flex flex-wrap gap-2">
              {group.values.map((value) => (
                <span
                  key={value}
                  className="border border-black bg-background px-2 py-1 font-mono text-xs"
                >
                  {value}
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
    );
  }

  return (
    <>
      {section.entries.map((entry) => (
        <div key={entry.id} className="mt-2">
          <p className="font-sans text-sm font-bold">
            {[entry.title, entry.subtitle].filter(Boolean).join(' · ')}
          </p>
          {entry.period.trim() && (
            <p className="font-mono text-xs text-steel-grey">{entry.period}</p>
          )}
          {entry.summary.trim() && (
            <p className="mt-1 font-sans text-xs leading-snug">{entry.summary}</p>
          )}
          <ul className="mt-1 list-none space-y-1">
            {entry.bullets.map((bullet, index) => (
              <li key={index} className="font-sans text-xs leading-snug">
                {bullet.text}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </>
  );
}
