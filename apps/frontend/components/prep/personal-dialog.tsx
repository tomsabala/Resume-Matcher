'use client';

import React, { useEffect, useState } from 'react';
import Loader2 from 'lucide-react/dist/esm/icons/loader-2';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { useTranslations } from '@/lib/i18n';
import {
  answerPrepCard,
  critiquePrepCard,
  updatePrepCard,
  type PrepCard,
} from '@/lib/api/prep-cards';

interface PersonalDialogProps {
  card: PrepCard;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUpdated: () => void;
}

/** Personal cards are rehearsed, not flipped: write an answer, then have it reviewed. */
export function PersonalDialog({ card, open, onOpenChange, onUpdated }: PersonalDialogProps) {
  const { t } = useTranslations();
  const [current, setCurrent] = useState<PrepCard>(card);
  const [myAnswer, setMyAnswer] = useState(card.my_answer ?? '');
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setCurrent(card);
    setMyAnswer(card.my_answer ?? '');
    setSaved(false);
    setError(null);
  }, [open, card]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter') e.stopPropagation();
  };

  // Each mutation replaces the local card so the dialog shows the server's copy
  // without waiting for the parent's reload to come back.
  const run = async (action: () => Promise<PrepCard>, failureKey: string) => {
    setBusy(true);
    setError(null);
    try {
      setCurrent(await action());
      onUpdated();
      return true;
    } catch {
      setError(t(failureKey));
      return false;
    } finally {
      setBusy(false);
    }
  };

  const handleSave = async () => {
    const ok = await run(
      () => updatePrepCard(current.card_id, { my_answer: myAnswer }),
      'prepDeck.errors.saveFailed'
    );
    setSaved(ok);
  };

  const handleCritique = async () => {
    setSaved(false);
    await run(() => critiquePrepCard(current.card_id, myAnswer), 'prepDeck.errors.critiqueFailed');
  };

  const handleGenerateAnswer = async () => {
    setSaved(false);
    await run(() => answerPrepCard(current.card_id), 'prepDeck.errors.answerFailed');
  };

  const critique = current.critique;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="font-serif text-xl font-bold leading-tight">
            {current.question}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          {current.answer ? (
            <div className="space-y-1 border border-black bg-paper-tint p-3">
              <p className="font-mono text-xs uppercase tracking-wide text-ink-soft">
                {t('prepDeck.card.explanation')}
              </p>
              <p className="whitespace-pre-wrap text-sm leading-relaxed">{current.answer}</p>
            </div>
          ) : (
            <Button variant="outline" onClick={handleGenerateAnswer} disabled={busy}>
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                t('prepDeck.card.generateAnswer')
              )}
            </Button>
          )}

          <div className="space-y-1">
            <Label htmlFor="prep-my-answer">{t('prepDeck.personal.myAnswer')}</Label>
            <Textarea
              id="prep-my-answer"
              value={myAnswer}
              onChange={(e) => {
                setMyAnswer(e.target.value);
                setSaved(false);
              }}
              onKeyDown={handleKeyDown}
              className="min-h-[8rem]"
            />
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={handleSave} disabled={busy}>
              {t('prepDeck.personal.save')}
            </Button>
            <Button
              variant="outline"
              onClick={handleCritique}
              disabled={busy || myAnswer.trim().length === 0}
            >
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                t('prepDeck.personal.getFeedback')
              )}
            </Button>
            {saved && (
              <span className="font-mono text-xs uppercase tracking-wide text-success">
                {t('prepDeck.personal.saved')}
              </span>
            )}
          </div>

          {critique ? (
            <div className="space-y-3 border-t border-black pt-4">
              <p className="font-mono text-xs uppercase tracking-wide text-ink-soft">
                {t('prepDeck.personal.critiqueScore')}: {critique.score}/5
              </p>
              {critique.strengths.length > 0 && (
                <div className="space-y-1">
                  <p className="font-mono text-xs uppercase tracking-wide text-ink-soft">
                    {t('prepDeck.personal.strengths')}
                  </p>
                  <ul className="list-disc space-y-1 pl-5 text-sm leading-relaxed">
                    {critique.strengths.map((item, i) => (
                      <li key={i}>{item}</li>
                    ))}
                  </ul>
                </div>
              )}
              {critique.gaps.length > 0 && (
                <div className="space-y-1">
                  <p className="font-mono text-xs uppercase tracking-wide text-ink-soft">
                    {t('prepDeck.personal.gaps')}
                  </p>
                  <ul className="list-disc space-y-1 pl-5 text-sm leading-relaxed">
                    {critique.gaps.map((item, i) => (
                      <li key={i}>{item}</li>
                    ))}
                  </ul>
                </div>
              )}
              <div className="space-y-1">
                <p className="font-mono text-xs uppercase tracking-wide text-ink-soft">
                  {t('prepDeck.personal.suggestedRewrite')}
                </p>
                <p className="whitespace-pre-wrap text-sm leading-relaxed">
                  {critique.suggested_rewrite}
                </p>
              </div>
            </div>
          ) : (
            <p className="font-mono text-xs uppercase tracking-wide text-ink-soft">
              {t('prepDeck.personal.noFeedback')}
            </p>
          )}

          {error && <p className="font-mono text-xs text-destructive">{error}</p>}
        </div>
      </DialogContent>
    </Dialog>
  );
}
