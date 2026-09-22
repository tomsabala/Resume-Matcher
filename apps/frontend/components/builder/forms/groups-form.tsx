'use client';

import React from 'react';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Plus, Trash2 } from 'lucide-react';
import { useTranslations } from '@/lib/i18n';
import type { TagGroup } from '@/lib/types/document';
import type { SectionFormProps } from './types';

/**
 * Editor for a `groups` section: labelled buckets of values.
 *
 * Labels are free text — "Languages", "Cloud", "Instruments". Nothing here
 * knows or cares which labels a given resume uses.
 */
export const GroupsForm: React.FC<SectionFormProps> = ({ section, onChange }) => {
  const { t } = useTranslations();

  const replaceGroups = (groups: TagGroup[]) => onChange({ ...section, groups });

  const updateGroup = (index: number, patch: Partial<TagGroup>) =>
    replaceGroups(section.groups.map((group, i) => (i === index ? { ...group, ...patch } : group)));

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button
          variant="outline"
          size="sm"
          onClick={() => replaceGroups([...section.groups, { label: '', values: [] }])}
          className="rounded-none border-black hover:bg-black hover:text-white transition-colors"
        >
          <Plus className="w-4 h-4 mr-2" /> {t('builder.sectionForms.groups.addGroup')}
        </Button>
      </div>

      <div className="space-y-6">
        {section.groups.map((group, index) => (
          <div
            key={index}
            className="p-6 border border-black bg-paper-tint relative group space-y-4"
          >
            <Button
              variant="ghost"
              size="icon"
              className="absolute top-2 right-2 opacity-100 transition-opacity text-destructive hover:text-destructive hover:bg-destructive/10 lg:opacity-0 lg:group-hover:opacity-100 lg:focus-visible:opacity-100"
              onClick={() => replaceGroups(section.groups.filter((_, i) => i !== index))}
              aria-label={t('builder.sectionForms.groups.removeGroup')}
              title={t('builder.sectionForms.groups.removeGroup')}
            >
              <Trash2 className="w-4 h-4" />
            </Button>

            <div className="space-y-2 pr-8">
              <Label className="font-mono text-xs uppercase tracking-wider text-steel-grey">
                {t('builder.sectionForms.groups.fields.label')}
              </Label>
              <Input
                value={group.label}
                onChange={(e) => updateGroup(index, { label: e.target.value })}
                placeholder={t('builder.sectionForms.groups.placeholders.label')}
                className="rounded-none border-black bg-white"
              />
            </div>

            <div className="space-y-2">
              <Label className="font-mono text-xs uppercase tracking-wider text-steel-grey">
                {t('builder.sectionForms.groups.fields.values')}
              </Label>
              <p className="font-mono text-xs uppercase tracking-wider text-blue-700">
                {t('builder.sectionForms.groups.instructions')}
              </p>
              <Textarea
                value={group.values.join('\n')}
                onChange={(e) =>
                  updateGroup(index, {
                    values: e.target.value.split('\n').filter((value) => value.trim() !== ''),
                  })
                }
                onKeyDown={(e) => {
                  if (e.key === 'Enter') e.stopPropagation();
                }}
                placeholder={t('builder.sectionForms.groups.placeholders.values')}
                className="min-h-[110px] text-black rounded-none border-black bg-white focus-visible:ring-0 focus-visible:ring-offset-0 focus-visible:border-blue-700"
              />
            </div>
          </div>
        ))}

        {section.groups.length === 0 && (
          <div className="text-center py-10 border border-dashed border-steel-grey">
            <p className="font-mono text-xs uppercase tracking-wider text-steel-grey mb-4">
              {t('builder.sectionForms.groups.noGroups')}
            </p>
            <Button
              variant="outline"
              size="sm"
              onClick={() => replaceGroups([{ label: '', values: [] }])}
              className="rounded-none border-black hover:bg-black hover:text-white transition-colors"
            >
              <Plus className="w-4 h-4 mr-2" /> {t('builder.sectionForms.groups.addFirstGroup')}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
};
