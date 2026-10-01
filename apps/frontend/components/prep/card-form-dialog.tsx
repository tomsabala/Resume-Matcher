'use client';

import React, { useEffect, useState } from 'react';
import Loader2 from 'lucide-react/dist/esm/icons/loader-2';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Segmented } from '@/components/ui/segmented';
import { Textarea } from '@/components/ui/textarea';
import { useTranslations } from '@/lib/i18n';
import {
  createPrepCard,
  updatePrepCard,
  type PrepCard,
  type PrepCardCategory,
} from '@/lib/api/prep-cards';

interface CardFormDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Null adds a card; a card edits it. */
  card: PrepCard | null;
  /** Category preselected for a new card. */
  defaultCategory: PrepCardCategory;
  onSaved: () => void;
}

export function CardFormDialog({
  open,
  onOpenChange,
  card,
  defaultCategory,
  onSaved,
}: CardFormDialogProps) {
  const { t } = useTranslations();
  const [category, setCategory] = useState<PrepCardCategory>(defaultCategory);
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset to the edited card (or a blank form) each time the dialog opens.
  useEffect(() => {
    if (!open) return;
    setCategory(card ? card.category : defaultCategory);
    setQuestion(card?.question ?? '');
    setAnswer(card?.answer ?? '');
    setError(null);
  }, [open, card, defaultCategory]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter') e.stopPropagation();
  };

  const handleSubmit = async () => {
    if (!question.trim()) {
      setError(t('prepDeck.form.questionRequired'));
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const payload = {
        category,
        question: question.trim(),
        answer: answer.trim() || null,
      };
      if (card) {
        await updatePrepCard(card.card_id, payload);
      } else {
        await createPrepCard(payload);
      }
      onSaved();
      onOpenChange(false);
    } catch {
      setError(t('prepDeck.errors.saveFailed'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>
            {card ? t('prepDeck.form.editTitle') : t('prepDeck.form.title')}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-1">
            <Label>{t('prepDeck.form.category')}</Label>
            <Segmented
              ariaLabel={t('prepDeck.form.category')}
              value={category}
              onChange={(id) => setCategory(id as PrepCardCategory)}
              options={[
                { id: 'technical', label: t('prepDeck.categories.technical') },
                { id: 'personal', label: t('prepDeck.categories.personal') },
              ]}
            />
          </div>

          <div className="space-y-1">
            <Label htmlFor="prep-question">{t('prepDeck.form.question')}</Label>
            <Textarea
              id="prep-question"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={handleKeyDown}
              dir="auto"
              className="min-h-[5rem]"
            />
          </div>

          <div className="space-y-1">
            <Label htmlFor="prep-answer">{t('prepDeck.form.answer')}</Label>
            <Textarea
              id="prep-answer"
              value={answer}
              onChange={(e) => setAnswer(e.target.value)}
              onKeyDown={handleKeyDown}
              dir="auto"
              className="min-h-[7rem]"
            />
          </div>

          {error && <p className="font-mono text-xs text-destructive">{error}</p>}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t('prepDeck.form.cancel')}
          </Button>
          <Button onClick={handleSubmit} disabled={submitting}>
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : t('prepDeck.form.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
