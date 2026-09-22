'use client';

import React from 'react';
import dynamic from 'next/dynamic';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Dropdown } from '@/components/ui/dropdown';

// Lazy-load TipTap-based editor — keeps it out of the initial bundle.
const RichTextEditor = dynamic(
  () => import('@/components/ui/rich-text-editor').then((m) => m.RichTextEditor),
  {
    ssr: false,
    loading: () => (
      <div className="min-h-[100px] border border-black bg-transparent" aria-busy="true" />
    ),
  }
);
import { AlignLeft, List, Plus, Trash2 } from 'lucide-react';
import { useTranslations } from '@/lib/i18n';
import type { Entry, EntryLink } from '@/lib/types/document';
import {
  DndContext,
  closestCenter,
  MouseSensor,
  TouchSensor,
  KeyboardSensor,
  useSensor,
  useSensors,
  DragEndEvent,
} from '@dnd-kit/core';
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { DraggableListItem } from '../draggable-list-item';
import type { SectionFormProps } from './types';

const LINK_KINDS: EntryLink['kind'][] = ['github', 'website', 'linkedin', 'other'];

/**
 * Editor for an `entries` section.
 *
 * Field names are generic because the section is: `title`/`subtitle` is job
 * title/company, degree/institution or project/role depending on what the user
 * called the section. `period` is stored verbatim and never parsed.
 */
export const GenericItemForm: React.FC<SectionFormProps> = ({ section, onChange }) => {
  const { t } = useTranslations();
  const entries = section.entries;

  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 4 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 250, tolerance: 8 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );

  const replaceEntries = (next: Entry[]) => onChange({ ...section, entries: next });

  const updateEntry = (id: string, patch: Partial<Entry>) =>
    replaceEntries(entries.map((entry) => (entry.id === id ? { ...entry, ...patch } : entry)));

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;

    const oldIndex = entries.findIndex((entry) => entry.id === active.id);
    const newIndex = entries.findIndex((entry) => entry.id === over.id);
    if (oldIndex === -1 || newIndex === -1) return;

    replaceEntries(arrayMove(entries, oldIndex, newIndex));
  };

  const handleAdd = () =>
    replaceEntries([
      ...entries,
      {
        id: crypto.randomUUID(),
        title: '',
        subtitle: '',
        meta: '',
        period: '',
        links: [],
        summary: '',
        bullets: [{ text: '', style: 'bullet' }],
      },
    ]);

  const textField = (
    field: 'title' | 'subtitle' | 'meta' | 'period',
    value: string,
    onValue: (next: string) => void
  ) => (
    <div className="space-y-2">
      <Label className="font-mono text-xs uppercase tracking-wider text-steel-grey">
        {t(`builder.sectionForms.entries.fields.${field}`)}
      </Label>
      <Input
        value={value}
        onChange={(e) => onValue(e.target.value)}
        placeholder={t(`builder.sectionForms.entries.placeholders.${field}`)}
        className="rounded-none border-black bg-white"
      />
    </div>
  );

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button
          variant="outline"
          size="sm"
          onClick={handleAdd}
          className="rounded-none border-black hover:bg-black hover:text-white transition-colors"
        >
          <Plus className="w-4 h-4 mr-2" /> {t('builder.sectionForms.entries.addEntry')}
        </Button>
      </div>

      <DndContext
        id={`section-entries-${section.id}`}
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={handleDragEnd}
      >
        <SortableContext
          items={entries.map((entry) => entry.id)}
          strategy={verticalListSortingStrategy}
        >
          <div className="space-y-8">
            {entries.map((entry) => (
              <DraggableListItem key={entry.id} id={entry.id}>
                <div className="p-4 sm:p-6 border border-black bg-paper-tint relative group">
                  <Button
                    variant="ghost"
                    size="icon"
                    className="ml-auto flex opacity-100 transition-opacity text-destructive hover:text-destructive hover:bg-destructive/10 md:absolute md:top-2 md:right-2 lg:opacity-0 lg:group-hover:opacity-100 lg:focus-visible:opacity-100"
                    onClick={() => replaceEntries(entries.filter((item) => item.id !== entry.id))}
                    aria-label={t('builder.sectionForms.entries.removeEntry')}
                    title={t('builder.sectionForms.entries.removeEntry')}
                  >
                    <Trash2 className="w-4 h-4" />
                  </Button>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4 md:pr-10 lg:pr-8">
                    {textField('title', entry.title, (title) => updateEntry(entry.id, { title }))}
                    {textField('subtitle', entry.subtitle, (subtitle) =>
                      updateEntry(entry.id, { subtitle })
                    )}
                    {textField('meta', entry.meta, (meta) => updateEntry(entry.id, { meta }))}
                    {textField('period', entry.period, (period) =>
                      updateEntry(entry.id, { period })
                    )}
                  </div>

                  <div className="space-y-2 mb-4">
                    <Label className="font-mono text-xs uppercase tracking-wider text-steel-grey">
                      {t('builder.sectionForms.entries.fields.summary')}
                    </Label>
                    <Textarea
                      value={entry.summary}
                      onChange={(e) => updateEntry(entry.id, { summary: e.target.value })}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') e.stopPropagation();
                      }}
                      placeholder={t('builder.sectionForms.entries.placeholders.summary')}
                      className="min-h-[70px] text-black rounded-none border-black bg-white focus-visible:ring-0 focus-visible:ring-offset-0 focus-visible:border-blue-700"
                    />
                  </div>

                  <div className="space-y-3 mb-4">
                    <div className="flex justify-between items-center">
                      <Label className="font-mono text-xs uppercase tracking-wider text-steel-grey">
                        {t('builder.sectionForms.entries.fields.links')}
                      </Label>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() =>
                          updateEntry(entry.id, {
                            links: [...entry.links, { kind: 'website', url: '' }],
                          })
                        }
                        className="h-6 text-xs text-blue-700 hover:text-blue-800 hover:bg-blue-50"
                      >
                        <Plus className="w-3 h-3 mr-1" />{' '}
                        {t('builder.sectionForms.entries.actions.addLink')}
                      </Button>
                    </div>
                    {entry.links.map((link, linkIndex) => (
                      <div
                        key={linkIndex}
                        className="flex flex-col gap-2 sm:flex-row sm:items-center"
                      >
                        <div className="w-full sm:w-40 sm:shrink-0">
                          <Dropdown
                            options={LINK_KINDS.map((kind) => ({
                              id: kind,
                              label: t(`builder.sectionForms.linkKinds.${kind}`),
                            }))}
                            value={link.kind}
                            onChange={(kind) =>
                              updateEntry(entry.id, {
                                links: entry.links.map((item, i) =>
                                  i === linkIndex
                                    ? { ...item, kind: kind as EntryLink['kind'] }
                                    : item
                                ),
                              })
                            }
                          />
                        </div>
                        <Input
                          value={link.url}
                          onChange={(e) =>
                            updateEntry(entry.id, {
                              links: entry.links.map((item, i) =>
                                i === linkIndex ? { ...item, url: e.target.value } : item
                              ),
                            })
                          }
                          placeholder={t('builder.sectionForms.entries.placeholders.linkUrl')}
                          className="rounded-none border-black bg-white"
                        />
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() =>
                            updateEntry(entry.id, {
                              links: entry.links.filter((_, i) => i !== linkIndex),
                            })
                          }
                          className="w-8 text-muted-foreground hover:text-destructive"
                          aria-label={t('builder.sectionForms.entries.actions.removeLink')}
                          title={t('builder.sectionForms.entries.actions.removeLink')}
                        >
                          <Trash2 className="w-3 h-3" />
                        </Button>
                      </div>
                    ))}
                  </div>

                  <div className="space-y-3">
                    <div className="flex justify-between items-center">
                      <Label className="font-mono text-xs uppercase tracking-wider text-steel-grey">
                        {t('builder.sectionForms.entries.fields.bullets')}
                      </Label>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() =>
                          updateEntry(entry.id, {
                            bullets: [...entry.bullets, { text: '', style: 'bullet' }],
                          })
                        }
                        className="h-6 text-xs text-blue-700 hover:text-blue-800 hover:bg-blue-50"
                      >
                        <Plus className="w-3 h-3 mr-1" />{' '}
                        {t('builder.sectionForms.entries.actions.addBullet')}
                      </Button>
                    </div>
                    {entry.bullets.map((bullet, bulletIndex) => (
                      <div
                        key={bulletIndex}
                        className="flex flex-col gap-1 sm:flex-row sm:items-start sm:gap-2"
                      >
                        <div className="min-w-0 flex-1">
                          <RichTextEditor
                            value={bullet.text}
                            onChange={(html) =>
                              updateEntry(entry.id, {
                                bullets: entry.bullets.map((item, i) =>
                                  i === bulletIndex ? { ...item, text: html } : item
                                ),
                              })
                            }
                            placeholder={t('builder.sectionForms.entries.placeholders.bullet')}
                            minHeight="60px"
                          />
                        </div>
                        {/* `sm:contents` hands both controls back to the row at
                            sm and up, so the desktop layout is untouched. */}
                        <div className="flex shrink-0 gap-1 sm:contents">
                          <Button
                            variant="ghost"
                            size="icon"
                            // The style travels with the row, so removing a
                            // neighbour can no longer shift it onto another line.
                            onClick={() =>
                              updateEntry(entry.id, {
                                bullets: entry.bullets.map((item, i) =>
                                  i === bulletIndex
                                    ? {
                                        ...item,
                                        style: item.style === 'plain' ? 'bullet' : 'plain',
                                      }
                                    : item
                                ),
                              })
                            }
                            className="h-11 w-11 text-muted-foreground hover:text-primary self-end"
                            aria-label={t('builder.sectionForms.entries.actions.toggleBulletStyle')}
                            title={t('builder.sectionForms.entries.actions.toggleBulletStyle')}
                            aria-pressed={bullet.style === 'plain'}
                          >
                            {bullet.style === 'plain' ? (
                              <AlignLeft className="w-3 h-3" />
                            ) : (
                              <List className="w-3 h-3" />
                            )}
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() =>
                              updateEntry(entry.id, {
                                bullets: entry.bullets.filter((_, i) => i !== bulletIndex),
                              })
                            }
                            className="h-11 w-11 text-muted-foreground hover:text-destructive self-end"
                            aria-label={t('builder.sectionForms.entries.actions.removeBullet')}
                            title={t('builder.sectionForms.entries.actions.removeBullet')}
                          >
                            <Trash2 className="w-3 h-3" />
                          </Button>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </DraggableListItem>
            ))}
          </div>
        </SortableContext>
      </DndContext>

      {entries.length === 0 && (
        <div className="text-center py-10 border border-dashed border-steel-grey">
          <p className="font-mono text-xs uppercase tracking-wider text-steel-grey mb-4">
            {t('builder.sectionForms.entries.noEntries')}
          </p>
          <Button
            variant="outline"
            size="sm"
            onClick={handleAdd}
            className="rounded-none border-black hover:bg-black hover:text-white transition-colors"
          >
            <Plus className="w-4 h-4 mr-2" /> {t('builder.sectionForms.entries.addFirstEntry')}
          </Button>
        </div>
      )}
    </div>
  );
};
