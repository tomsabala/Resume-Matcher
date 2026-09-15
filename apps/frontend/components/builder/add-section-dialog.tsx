'use client';

import React, { useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Plus, FileText, List, ListOrdered, LayoutList } from 'lucide-react';
import type { SectionKind } from '@/lib/types/document';
import { useTranslations } from '@/lib/i18n';

interface AddSectionDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAdd: (heading: string, kind: SectionKind) => void;
}

const KIND_ICONS: Record<SectionKind, React.ReactNode> = {
  text: <FileText className="w-5 h-5" />,
  entries: <ListOrdered className="w-5 h-5" />,
  tags: <List className="w-5 h-5" />,
  groups: <LayoutList className="w-5 h-5" />,
};

const KIND_ORDER: SectionKind[] = ['text', 'entries', 'tags', 'groups'];

/**
 * Creates a section: a heading and a content shape. Every section in the
 * document is created this way — there is no privileged built-in set.
 */
export const AddSectionDialog: React.FC<AddSectionDialogProps> = ({
  open,
  onOpenChange,
  onAdd,
}) => {
  const { t } = useTranslations();
  const [heading, setHeading] = useState('');
  const [kind, setKind] = useState<SectionKind>('text');

  const handleSubmit = () => {
    if (heading.trim()) {
      onAdd(heading.trim(), kind);
      setHeading('');
      setKind('text');
      onOpenChange(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px] p-0 gap-0 rounded-none">
        <DialogHeader className="p-6 pb-4 border-b border-black">
          <DialogTitle className="font-serif text-xl font-bold uppercase tracking-tight">
            {t('builder.addSectionDialog.title')}
          </DialogTitle>
          <DialogDescription className="font-mono text-xs text-ink-soft mt-2">
            {t('builder.addSectionDialog.description')}
          </DialogDescription>
        </DialogHeader>

        <div className="p-6 space-y-6">
          <div className="space-y-2">
            <Label className="font-mono text-xs uppercase tracking-wider text-steel-grey">
              {t('builder.addSectionDialog.headingLabel')}
            </Label>
            <Input
              value={heading}
              onChange={(e) => setHeading(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && heading.trim()) handleSubmit();
              }}
              placeholder={t('builder.addSectionDialog.headingPlaceholder')}
              className="rounded-none border-black"
              autoFocus
            />
          </div>

          <div className="space-y-3">
            <Label className="font-mono text-xs uppercase tracking-wider text-steel-grey">
              {t('builder.addSectionDialog.kindLabel')}
            </Label>
            <div className="space-y-2">
              {KIND_ORDER.map((option) => (
                <button
                  key={option}
                  type="button"
                  onClick={() => setKind(option)}
                  aria-pressed={kind === option}
                  className={`w-full p-4 border text-left transition-colors ${
                    kind === option
                      ? 'border-black bg-paper-tint shadow-sw-sm'
                      : 'border-steel-grey hover:border-steel-grey'
                  }`}
                >
                  <div className="flex items-start gap-3">
                    <div
                      className={`p-2 border ${
                        kind === option
                          ? 'border-black bg-white'
                          : 'border-steel-grey bg-paper-tint'
                      }`}
                    >
                      {KIND_ICONS[option]}
                    </div>
                    <div className="flex-1">
                      <div className="font-sans font-medium text-sm">
                        {t(`builder.sectionForms.kinds.${option}.label`)}
                      </div>
                      <div className="font-mono text-xs text-steel-grey mt-0.5">
                        {t(`builder.sectionForms.kinds.${option}.description`)}
                      </div>
                    </div>
                    {kind === option && <div className="w-4 h-4 border-2 border-black bg-black" />}
                  </div>
                </button>
              ))}
            </div>
          </div>
        </div>

        <DialogFooter className="p-4 bg-background border-t border-black flex-row justify-end gap-3">
          <DialogClose asChild>
            <Button variant="outline" className="rounded-none border-black">
              {t('common.cancel')}
            </Button>
          </DialogClose>
          <Button onClick={handleSubmit} disabled={!heading.trim()} className="rounded-none">
            <Plus className="w-4 h-4 mr-2" />
            {t('builder.addSection')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

interface AddSectionButtonProps {
  onAdd: (heading: string, kind: SectionKind) => void;
}

export const AddSectionButton: React.FC<AddSectionButtonProps> = ({ onAdd }) => {
  const { t } = useTranslations();
  const [open, setOpen] = useState(false);

  return (
    <>
      <Button
        variant="outline"
        onClick={() => setOpen(true)}
        className="w-full rounded-none border-dashed border-2 border-black py-6 hover:bg-paper-tint hover:border-solid transition-all"
      >
        <Plus className="w-5 h-5 mr-2" />
        {t('builder.addSection')}
      </Button>
      <AddSectionDialog open={open} onOpenChange={setOpen} onAdd={onAdd} />
    </>
  );
};
