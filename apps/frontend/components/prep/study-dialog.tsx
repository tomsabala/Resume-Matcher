'use client';

import React, { useEffect, useState } from 'react';
import Loader2 from 'lucide-react/dist/esm/icons/loader-2';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { useTranslations } from '@/lib/i18n';
import {
  answerPrepCard,
  updatePrepCard,
  type PrepCard,
  type PrepCardConfidence,
} from '@/lib/api/prep-cards';

interface StudyDialogProps {
  cards: PrepCard[];
  startIndex: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onRated: () => void;
}

const RATINGS: PrepCardConfidence[] = ['again', 'good', 'easy'];

/**
 * The flip-card game. The faces swap instantly — the design system forbids
 * animated transitions, so there is no CSS 3D flip here.
 */
export function StudyDialog({ cards, startIndex, open, onOpenChange, onRated }: StudyDialogProps) {
  const { t } = useTranslations();
  const [index, setIndex] = useState(startIndex);
  const [revealed, setRevealed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // The answer generated in-session, rendered in place of the stored null.
  const [generated, setGenerated] = useState<PrepCard | null>(null);

  useEffect(() => {
    if (open) setIndex(startIndex);
  }, [open, startIndex]);

  // A new card always starts face-down.
  useEffect(() => {
    setRevealed(false);
    setGenerated(null);
    setError(null);
  }, [index]);

  const stored = cards[index];
  const card = generated && stored && generated.card_id === stored.card_id ? generated : stored;
  if (!card) return null;

  const advance = () => {
    if (index + 1 >= cards.length) {
      onOpenChange(false);
      return;
    }
    setIndex(index + 1);
  };

  const handleRate = async (confidence: PrepCardConfidence) => {
    setBusy(true);
    setError(null);
    try {
      await updatePrepCard(card.card_id, { confidence });
      onRated();
      advance();
    } catch {
      setError(t('prepDeck.errors.saveFailed'));
    } finally {
      setBusy(false);
    }
  };

  const handleGenerateAnswer = async () => {
    setBusy(true);
    setError(null);
    try {
      setGenerated(await answerPrepCard(card.card_id));
      onRated();
    } catch {
      setError(t('prepDeck.errors.answerFailed'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="font-mono text-xs uppercase tracking-wide">
            {t('prepDeck.study.progress', { current: index + 1, total: cards.length })}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          <p className="font-serif text-2xl font-bold leading-tight">{card.question}</p>

          {!revealed ? (
            <Button onClick={() => setRevealed(true)}>{t('prepDeck.card.reveal')}</Button>
          ) : (
            <div className="space-y-4 border-t border-black pt-4">
              {card.answer ? (
                <>
                  <p className="whitespace-pre-wrap text-base leading-relaxed">{card.answer}</p>
                  {card.explanation && (
                    <div className="space-y-1">
                      <p className="font-mono text-xs uppercase tracking-wide text-ink-soft">
                        {t('prepDeck.card.explanation')}
                      </p>
                      <p className="whitespace-pre-wrap text-sm leading-relaxed">
                        {card.explanation}
                      </p>
                    </div>
                  )}
                  {card.examples && card.examples.length > 0 && (
                    <div className="space-y-1">
                      <p className="font-mono text-xs uppercase tracking-wide text-ink-soft">
                        {t('prepDeck.card.examples')}
                      </p>
                      <ul className="list-disc space-y-1 pl-5 text-sm leading-relaxed">
                        {card.examples.map((example, i) => (
                          <li key={i}>{example}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </>
              ) : (
                <div className="space-y-2">
                  <p className="font-mono text-xs uppercase tracking-wide text-ink-soft">
                    {t('prepDeck.card.noAnswer')}
                  </p>
                  <Button variant="outline" onClick={handleGenerateAnswer} disabled={busy}>
                    {busy ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      t('prepDeck.card.generateAnswer')
                    )}
                  </Button>
                </div>
              )}

              <div className="space-y-2">
                <p className="font-mono text-xs uppercase tracking-wide text-ink-soft">
                  {t('prepDeck.study.rate')}
                </p>
                <div className="flex flex-wrap gap-2">
                  {RATINGS.map((rating) => (
                    <Button
                      key={rating}
                      variant="outline"
                      disabled={busy}
                      onClick={() => handleRate(rating)}
                    >
                      {t(`prepDeck.confidence.${rating}`)}
                    </Button>
                  ))}
                </div>
              </div>
            </div>
          )}

          {error && <p className="font-mono text-xs text-destructive">{error}</p>}
        </div>
      </DialogContent>
    </Dialog>
  );
}
