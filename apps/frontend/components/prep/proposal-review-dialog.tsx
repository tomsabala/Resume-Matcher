'use client';

import React, { useEffect, useState } from 'react';
import Loader2 from 'lucide-react/dist/esm/icons/loader-2';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Segmented } from '@/components/ui/segmented';
import { useTranslations } from '@/lib/i18n';
import type { PrepCardCategory, PrepCardCreate, PrepCardProposal } from '@/lib/api/prep-cards';

interface ProposalReviewDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  proposals: PrepCardProposal[];
  /** True while the proposals are still being generated. */
  loading: boolean;
  title: string;
  description?: string;
  onAccept: (accepted: PrepCardCreate[]) => Promise<void>;
}

/**
 * The review-before-save step, shared by AI generation and the builder import.
 * Every proposal starts checked, and its category can be flipped before saving.
 */
export function ProposalReviewDialog({
  open,
  onOpenChange,
  proposals,
  loading,
  title,
  description,
  onAccept,
}: ProposalReviewDialogProps) {
  const { t } = useTranslations();
  const [checked, setChecked] = useState<boolean[]>([]);
  const [categories, setCategories] = useState<PrepCardCategory[]>([]);
  const [saving, setSaving] = useState(false);

  // A fresh batch resets the selection: indices from the previous one are
  // meaningless against new proposals.
  useEffect(() => {
    setChecked(proposals.map(() => true));
    setCategories(proposals.map((p) => p.category));
  }, [proposals]);

  const allChecked = checked.length > 0 && checked.every(Boolean);

  const toggleAll = () => {
    setChecked(proposals.map(() => !allChecked));
  };

  const toggleOne = (index: number) => {
    setChecked((prev) => prev.map((value, i) => (i === index ? !value : value)));
  };

  const setCategory = (index: number, category: PrepCardCategory) => {
    setCategories((prev) => prev.map((value, i) => (i === index ? category : value)));
  };

  const handleAccept = async () => {
    const accepted: PrepCardCreate[] = proposals
      .map((proposal, index) => ({
        category: categories[index] ?? proposal.category,
        question: proposal.question,
        explanation: proposal.explanation,
      }))
      .filter((_, index) => checked[index]);
    if (accepted.length === 0) return;
    setSaving(true);
    try {
      await onAccept(accepted);
    } finally {
      setSaving(false);
    }
  };

  const selectedCount = checked.filter(Boolean).length;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description ? <DialogDescription>{description}</DialogDescription> : null}
        </DialogHeader>

        {loading ? (
          <div className="flex items-center justify-center py-10">
            <Loader2 className="h-6 w-6 animate-spin" />
          </div>
        ) : proposals.length === 0 ? (
          <p className="py-6 font-mono text-xs uppercase tracking-wide text-ink-soft">
            {t('prepDeck.generateDialog.empty')}
          </p>
        ) : (
          <div className="space-y-3">
            <button
              type="button"
              onClick={toggleAll}
              className="font-mono text-xs uppercase tracking-wide text-ink-soft hover:text-primary"
            >
              {t('prepDeck.generateDialog.selectAll')}
            </button>
            <ul className="max-h-[22rem] space-y-2 overflow-y-auto">
              {proposals.map((proposal, index) => (
                <li
                  key={`${proposal.question}-${index}`}
                  className="flex items-start gap-3 border border-black bg-white p-3"
                >
                  <input
                    type="checkbox"
                    aria-label={proposal.question}
                    checked={checked[index] ?? false}
                    onChange={() => toggleOne(index)}
                    className="mt-1 h-4 w-4 shrink-0 accent-black"
                  />
                  <div className="min-w-0 flex-1 space-y-2">
                    <p className="text-sm font-bold leading-snug">{proposal.question}</p>
                    {proposal.explanation && (
                      <p className="whitespace-pre-wrap text-xs leading-relaxed text-ink-soft">
                        {proposal.explanation}
                      </p>
                    )}
                    <Segmented
                      ariaLabel={t('prepDeck.form.category')}
                      value={categories[index] ?? proposal.category}
                      onChange={(id) => setCategory(index, id as PrepCardCategory)}
                      className="max-w-xs"
                      options={[
                        { id: 'technical', label: t('prepDeck.categories.technical') },
                        { id: 'personal', label: t('prepDeck.categories.personal') },
                      ]}
                    />
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}

        <DialogFooter>
          <Button onClick={handleAccept} disabled={loading || saving || selectedCount === 0}>
            {saving ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              t('prepDeck.generateDialog.accept')
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
