'use client';

import React from 'react';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { useTranslations } from '@/lib/i18n';
import type { SectionFormProps } from './types';

/** Editor for a `text` section: one block of prose. */
export const GenericTextForm: React.FC<SectionFormProps> = ({ section, onChange }) => {
  const { t } = useTranslations();

  return (
    <div className="space-y-2">
      <Label className="font-mono text-xs uppercase tracking-wider text-steel-grey">
        {t('builder.sectionForms.text.label')}
      </Label>
      <Textarea
        value={section.text}
        onChange={(e) => onChange({ ...section, text: e.target.value })}
        onKeyDown={(e) => {
          // The section list is drag-and-drop sortable; an un-stopped Enter is
          // interpreted as "drop here" instead of a newline.
          if (e.key === 'Enter') e.stopPropagation();
        }}
        placeholder={t('builder.sectionForms.text.placeholder')}
        className="min-h-[150px] text-black rounded-none border-black focus-visible:ring-0 focus-visible:ring-offset-0 focus-visible:border-blue-700 bg-white"
      />
    </div>
  );
};
