'use client';

import React from 'react';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { useTranslations } from '@/lib/i18n';
import type { SectionFormProps } from './types';

/** Editor for a `tags` section: a flat list of short values, one per line. */
export const GenericListForm: React.FC<SectionFormProps> = ({ section, onChange }) => {
  const { t } = useTranslations();

  return (
    <div className="space-y-2">
      <Label className="font-mono text-xs uppercase tracking-wider text-steel-grey">
        {t('builder.sectionForms.tags.label')}
      </Label>
      <p className="font-mono text-xs uppercase tracking-wider text-blue-700 mb-2">
        {t('builder.sectionForms.tags.instructions')}
      </p>
      <Textarea
        value={section.tags.join('\n')}
        // Blank lines are dropped on the way out, so a trailing newline while
        // typing never persists as an empty tag.
        onChange={(e) =>
          onChange({
            ...section,
            tags: e.target.value.split('\n').filter((tag) => tag.trim() !== ''),
          })
        }
        onKeyDown={(e) => {
          if (e.key === 'Enter') e.stopPropagation();
        }}
        placeholder={t('builder.sectionForms.tags.placeholder')}
        className="min-h-[150px] text-black rounded-none border-black bg-white focus-visible:ring-0 focus-visible:ring-offset-0 focus-visible:border-blue-700"
      />
    </div>
  );
};
