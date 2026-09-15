'use client';

import React from 'react';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import { Dropdown } from '@/components/ui/dropdown';
import { Plus, Trash2 } from 'lucide-react';
import type { Contact, ContactKind, Header } from '@/lib/types/document';
import { useTranslations } from '@/lib/i18n';

const CONTACT_KINDS: ContactKind[] = [
  'email',
  'phone',
  'website',
  'github',
  'linkedin',
  'location',
  'other',
];

interface PersonalInfoFormProps {
  header: Header;
  onChange: (header: Header) => void;
}

/**
 * Editor for the document header.
 *
 * The header is not a section — it has no heading, no kind and no visibility,
 * and templates render it outside the section loop. Its contacts are a list, so
 * a resume can carry two websites or no phone at all.
 */
export const PersonalInfoForm: React.FC<PersonalInfoFormProps> = ({ header, onChange }) => {
  const { t } = useTranslations();

  const updateContact = (index: number, patch: Partial<Contact>) =>
    onChange({
      ...header,
      contacts: header.contacts.map((contact, i) =>
        i === index ? { ...contact, ...patch } : contact
      ),
    });

  return (
    <div className="space-y-4 border border-black p-6 bg-white shadow-sw-default">
      <h3 className="font-serif text-xl font-bold border-b border-black pb-2 mb-4">
        {t('builder.header.title')}
      </h3>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label
            htmlFor="header-name"
            className="font-mono text-xs uppercase tracking-wider text-steel-grey"
          >
            {t('builder.header.fields.name')}
          </Label>
          <Input
            id="header-name"
            value={header.name}
            onChange={(e) => onChange({ ...header, name: e.target.value })}
            placeholder={t('builder.header.placeholders.name')}
            className="rounded-none border-black focus-visible:ring-0 focus-visible:ring-offset-0 focus-visible:border-blue-700 bg-transparent"
          />
        </div>
        <div className="space-y-2">
          <Label
            htmlFor="header-headline"
            className="font-mono text-xs uppercase tracking-wider text-steel-grey"
          >
            {t('builder.header.fields.headline')}
          </Label>
          <Input
            id="header-headline"
            value={header.headline}
            onChange={(e) => onChange({ ...header, headline: e.target.value })}
            placeholder={t('builder.header.placeholders.headline')}
            className="rounded-none border-black focus-visible:ring-0 focus-visible:ring-offset-0 focus-visible:border-blue-700 bg-transparent"
          />
        </div>
      </div>

      <div className="space-y-3 pt-2">
        <div className="flex justify-between items-center">
          <Label className="font-mono text-xs uppercase tracking-wider text-steel-grey">
            {t('builder.header.fields.contacts')}
          </Label>
          <Button
            variant="ghost"
            size="sm"
            onClick={() =>
              onChange({
                ...header,
                contacts: [
                  ...header.contacts,
                  { id: crypto.randomUUID(), kind: 'email', label: '', value: '', url: '' },
                ],
              })
            }
            className="h-6 text-xs text-blue-700 hover:text-blue-800 hover:bg-blue-50"
          >
            <Plus className="w-3 h-3 mr-1" /> {t('builder.header.addContact')}
          </Button>
        </div>

        {header.contacts.map((contact, index) => (
          <div
            key={contact.id}
            className="grid grid-cols-1 md:grid-cols-[10rem_1fr_1fr_1fr_2rem] gap-2 items-center"
          >
            <Dropdown
              options={CONTACT_KINDS.map((kind) => ({
                id: kind,
                label: t(`builder.header.contactKinds.${kind}`),
              }))}
              value={contact.kind}
              onChange={(kind) => updateContact(index, { kind: kind as ContactKind })}
            />
            <Input
              value={contact.label}
              onChange={(e) => updateContact(index, { label: e.target.value })}
              placeholder={t('builder.header.placeholders.contactLabel')}
              aria-label={t('builder.header.fields.contactLabel')}
              className="rounded-none border-black bg-transparent"
            />
            <Input
              value={contact.value}
              onChange={(e) => updateContact(index, { value: e.target.value })}
              placeholder={t('builder.header.placeholders.contactValue')}
              aria-label={t('builder.header.fields.contactValue')}
              className="rounded-none border-black bg-transparent"
            />
            <Input
              value={contact.url}
              onChange={(e) => updateContact(index, { url: e.target.value })}
              placeholder={t('builder.header.placeholders.contactUrl')}
              aria-label={t('builder.header.fields.contactUrl')}
              className="rounded-none border-black bg-transparent"
            />
            <Button
              variant="ghost"
              size="icon"
              onClick={() =>
                onChange({ ...header, contacts: header.contacts.filter((_, i) => i !== index) })
              }
              className="w-8 text-muted-foreground hover:text-destructive"
              aria-label={t('builder.header.removeContact')}
              title={t('builder.header.removeContact')}
            >
              <Trash2 className="w-4 h-4" />
            </Button>
          </div>
        ))}

        {header.contacts.length === 0 && (
          <p className="font-mono text-xs uppercase tracking-wider text-steel-grey">
            {t('builder.header.noContacts')}
          </p>
        )}
      </div>
    </div>
  );
};
