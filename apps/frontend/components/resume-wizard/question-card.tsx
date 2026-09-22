'use client';

import { useState, type KeyboardEvent } from 'react';
import { ChevronLeft, MoreVertical } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { ActionSheet, type ActionSheetItem } from '@/components/ui/action-sheet';
import { MobileActionBar } from '@/components/common/mobile-action-bar';
import { useIsMobile } from '@/hooks/use-is-mobile';
import { useTranslations } from '@/lib/i18n';
import type { ResumeWizardProgress, ResumeWizardStep } from '@/lib/api/resume-wizard';

interface QuestionCardProps {
  step: ResumeWizardStep;
  question: string;
  sectionLabel: string;
  progress: ResumeWizardProgress;
  answer: string;
  onAnswerChange: (value: string) => void;
  canGoBack: boolean;
  isBusy: boolean;
  onContinue: () => void;
  onSkip: () => void;
  onBack: () => void;
  onReview: () => void;
  onFinalize: () => void;
  onKeepAdding: () => void;
  warnings: string[];
  /** AI's "you have enough to finish" signal — surfaces a ready hint on question steps. */
  isComplete?: boolean;
  /** Whether the draft can be finalized (e.g. has a name); gates the Create button. */
  canFinalize?: boolean;
  /** Opens the live preview as a sheet; the inline preview is desktop-only. */
  onPreview?: () => void;
}

export function QuestionCard({
  step,
  question,
  sectionLabel,
  progress,
  answer,
  onAnswerChange,
  canGoBack,
  isBusy,
  onContinue,
  onSkip,
  onBack,
  onReview,
  onFinalize,
  onKeepAdding,
  warnings,
  isComplete = false,
  canFinalize = true,
  onPreview,
}: QuestionCardProps) {
  const { t } = useTranslations();
  const isMobile = useIsMobile();
  const [mobileActionsOpen, setMobileActionsOpen] = useState(false);
  const isReview = step === 'review';
  const isQuestion = step === 'question';
  const canContinue = answer.trim().length > 0 && !isBusy;
  const totalSegments = Math.max(progress.total, 1);

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    // Repo pattern: never let Enter bubble to a parent form/dialog.
    if (event.key !== 'Enter') return;
    event.stopPropagation();
    // Enter submits, Shift+Enter inserts a newline.
    if (!event.shiftKey) {
      event.preventDefault();
      if (canContinue) onContinue();
    }
  };

  // Everything that is not the commit action moves off the thumb row on a phone.
  const mobileSheetItems: ActionSheetItem[] = [
    ...(onPreview
      ? [{ id: 'preview', label: t('builder.pane.preview'), onSelect: onPreview }]
      : []),
    ...(isReview
      ? [
          {
            id: 'keep-adding',
            label: t('resumeWizard.actions.keepAdding'),
            disabled: isBusy,
            onSelect: onKeepAdding,
          },
        ]
      : []),
    ...(isQuestion
      ? [
          {
            id: 'skip',
            label: t('resumeWizard.actions.skip'),
            disabled: isBusy,
            onSelect: onSkip,
          },
          {
            id: 'review',
            label: t('resumeWizard.actions.review'),
            disabled: isBusy,
            onSelect: onReview,
          },
        ]
      : []),
  ];

  return (
    <>
      <section className="border-2 border-black bg-white shadow-sw-lg">
        <div className="flex items-center gap-3 border-b-2 border-black p-2">
          <div
            className="flex flex-1 gap-1"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={totalSegments}
            aria-valuenow={progress.current}
          >
            {Array.from({ length: totalSegments }).map((_, index) => (
              <span
                key={index}
                className={
                  index < progress.current
                    ? 'h-1.5 flex-1 border border-black bg-black'
                    : 'h-1.5 flex-1 border border-black bg-white'
                }
              />
            ))}
          </div>
          <span className="font-mono text-xs uppercase tracking-wide text-ink-soft">
            {progress.current} / {totalSegments}
          </span>
        </div>

        <div className="grid gap-6 p-5 md:p-8">
          <p className="font-mono text-xs font-bold uppercase tracking-wider text-blue-700">
            {sectionLabel}
          </p>
          <h2 className="font-serif text-3xl font-bold leading-tight md:text-4xl">{question}</h2>

          {isReview ? (
            warnings.length > 0 && (
              <ul className="grid gap-2">
                {warnings.map((warning, index) => (
                  <li
                    key={index}
                    className="border border-steel-grey bg-white px-3 py-2 font-sans text-sm text-steel-grey"
                  >
                    {warning}
                  </li>
                ))}
              </ul>
            )
          ) : (
            <div className="grid gap-2">
              <label
                htmlFor="resume-wizard-answer"
                className="font-mono text-xs font-bold uppercase tracking-wider text-steel-grey"
              >
                {t('resumeWizard.answerLabel')}
              </label>
              <Textarea
                id="resume-wizard-answer"
                value={answer}
                onChange={(event) => onAnswerChange(event.target.value)}
                onKeyDown={handleKeyDown}
                disabled={isBusy}
                className="min-h-40 bg-white font-sans text-base"
              />
            </div>
          )}

          {isQuestion && isComplete && (
            <p className="flex items-center gap-2 font-mono text-xs font-bold uppercase tracking-wider text-green-700">
              <span aria-hidden="true" className="inline-block h-3 w-3 bg-green-700" />
              {t('resumeWizard.readyHint')}
            </p>
          )}

          <div className="hidden flex-wrap gap-3 border-t-2 border-black pt-5 lg:flex">
            {isReview ? (
              <>
                <Button
                  type="button"
                  variant="success"
                  onClick={onFinalize}
                  disabled={isBusy || !canFinalize}
                >
                  {isBusy ? t('common.saving') : t('resumeWizard.actions.create')}
                </Button>
                <Button type="button" variant="outline" onClick={onKeepAdding} disabled={isBusy}>
                  {t('resumeWizard.actions.keepAdding')}
                </Button>
              </>
            ) : (
              <>
                <Button type="button" onClick={onContinue} disabled={!canContinue}>
                  {isBusy ? t('common.loading') : t('resumeWizard.actions.continue')}
                </Button>
                {isQuestion && (
                  <Button type="button" variant="outline" onClick={onSkip} disabled={isBusy}>
                    {t('resumeWizard.actions.skip')}
                  </Button>
                )}
                {isQuestion && (
                  <Button type="button" variant="outline" onClick={onReview} disabled={isBusy}>
                    {t('resumeWizard.actions.review')}
                  </Button>
                )}
                {isQuestion && canGoBack && (
                  <Button type="button" variant="ghost" onClick={onBack} disabled={isBusy}>
                    {t('resumeWizard.actions.back')}
                  </Button>
                )}
              </>
            )}
          </div>
        </div>
      </section>

      {/* Runtime branch so each action exists exactly once in the DOM; the bar's
          negative gutters cancel the wizard page's own padding. */}
      {isMobile && (
        <>
          <MobileActionBar className="-mx-4 md:-mx-8">
            {isQuestion && canGoBack && (
              <button
                type="button"
                onClick={onBack}
                disabled={isBusy}
                aria-label={t('resumeWizard.actions.back')}
                className="flex h-11 w-11 shrink-0 items-center justify-center border border-black bg-background active:bg-secondary disabled:opacity-40"
              >
                <ChevronLeft className="h-5 w-5" />
              </button>
            )}
            {isReview ? (
              <Button
                type="button"
                variant="success"
                onClick={onFinalize}
                disabled={isBusy || !canFinalize}
                className="flex-1"
              >
                {isBusy ? t('common.saving') : t('resumeWizard.actions.create')}
              </Button>
            ) : (
              <Button type="button" onClick={onContinue} disabled={!canContinue} className="flex-1">
                {isBusy ? t('common.loading') : t('resumeWizard.actions.continue')}
              </Button>
            )}
            {mobileSheetItems.length > 0 && (
              <button
                type="button"
                onClick={() => setMobileActionsOpen(true)}
                aria-label={t('common.more')}
                className="flex h-11 w-11 shrink-0 items-center justify-center border border-black bg-background active:bg-secondary"
              >
                <MoreVertical className="h-5 w-5" />
              </button>
            )}
          </MobileActionBar>

          <ActionSheet
            open={mobileActionsOpen}
            onOpenChange={setMobileActionsOpen}
            title={sectionLabel}
            items={mobileSheetItems}
          />
        </>
      )}
    </>
  );
}
