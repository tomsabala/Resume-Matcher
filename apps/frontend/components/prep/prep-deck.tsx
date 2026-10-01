'use client';

import React, { useEffect, useMemo, useState } from 'react';
import Loader2 from 'lucide-react/dist/esm/icons/loader-2';
import MoreVertical from 'lucide-react/dist/esm/icons/more-vertical';
import { Button } from '@/components/ui/button';
import { ActionSheet } from '@/components/ui/action-sheet';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { ListRow } from '@/components/ui/list-row';
import { Segmented } from '@/components/ui/segmented';
import { useTranslations } from '@/lib/i18n';
import { useWorkspace } from '@/lib/context/workspace-context';
import {
  bulkCreatePrepCards,
  deletePrepCard,
  generatePrepCards,
  listPrepCards,
  type PrepCard,
  type PrepCardCategory,
  type PrepCardCreate,
  type PrepCardProposal,
} from '@/lib/api/prep-cards';
import { CardFormDialog } from './card-form-dialog';
import { PersonalDialog } from './personal-dialog';
import { ProposalReviewDialog } from './proposal-review-dialog';
import { StudyDialog } from './study-dialog';

// How many questions one "Generate" asks for.
const GENERATE_COUNT = 8;

export function PrepDeck() {
  const { t } = useTranslations();
  const { revision } = useWorkspace();

  const [cards, setCards] = useState<PrepCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [category, setCategory] = useState<PrepCardCategory>('technical');

  const [formCard, setFormCard] = useState<PrepCard | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [sheetCard, setSheetCard] = useState<PrepCard | null>(null);
  const [deleteCard, setDeleteCard] = useState<PrepCard | null>(null);
  const [studyIndex, setStudyIndex] = useState<number | null>(null);
  const [personalCard, setPersonalCard] = useState<PrepCard | null>(null);

  const [generateOpen, setGenerateOpen] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [proposals, setProposals] = useState<PrepCardProposal[]>([]);

  const load = async () => {
    try {
      const data = await listPrepCards();
      setCards(data.cards);
      setError(null);
    } catch {
      setError(t('prepDeck.errors.loadFailed'));
    } finally {
      setLoading(false);
    }
  };

  // Reruns when the header switcher selects another workspace.
  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [revision]);

  const visible = useMemo(
    () => cards.filter((card) => card.category === category),
    [cards, category]
  );

  const handleGenerate = async () => {
    setProposals([]);
    setGenerating(true);
    setGenerateOpen(true);
    try {
      const data = await generatePrepCards({ category, count: GENERATE_COUNT });
      setProposals(data.proposals);
      setError(null);
    } catch {
      setGenerateOpen(false);
      setError(t('prepDeck.errors.generateFailed'));
    } finally {
      setGenerating(false);
    }
  };

  const handleAcceptProposals = async (accepted: PrepCardCreate[]) => {
    try {
      await bulkCreatePrepCards(accepted);
      setGenerateOpen(false);
      await load();
    } catch {
      setError(t('prepDeck.errors.saveFailed'));
    }
  };

  const handleDelete = async () => {
    if (!deleteCard) return;
    try {
      await deletePrepCard(deleteCard.card_id);
      await load();
    } catch {
      setError(t('prepDeck.errors.deleteFailed'));
    } finally {
      setDeleteCard(null);
    }
  };

  const openCard = (index: number) => {
    if (category === 'technical') {
      setStudyIndex(index);
    } else {
      setPersonalCard(visible[index]);
    }
  };

  const actions = (
    <>
      <Button
        variant="outline"
        onClick={() => {
          setFormCard(null);
          setFormOpen(true);
        }}
      >
        {t('prepDeck.addCard')}
      </Button>
      <Button variant="outline" onClick={handleGenerate}>
        {t('prepDeck.generate')}
      </Button>
    </>
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="shrink-0 space-y-3 border-b border-black bg-background p-4">
        <div>
          <h1 className="font-serif text-2xl font-bold leading-tight">{t('prepDeck.title')}</h1>
          <p className="font-mono text-xs uppercase tracking-wide text-ink-soft">
            {t('prepDeck.subtitle')}
          </p>
        </div>
        <Segmented
          ariaLabel={t('prepDeck.title')}
          value={category}
          onChange={(id) => setCategory(id as PrepCardCategory)}
          className="max-w-sm"
          options={[
            { id: 'technical', label: t('prepDeck.categories.technical') },
            { id: 'personal', label: t('prepDeck.categories.personal') },
          ]}
        />
        <div className="flex flex-wrap items-center gap-2">
          {actions}
          {category === 'technical' && (
            <Button onClick={() => setStudyIndex(0)} disabled={visible.length === 0}>
              {t('prepDeck.studyAction')}
            </Button>
          )}
        </div>
        {error && <p className="font-mono text-xs text-destructive">{error}</p>}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {loading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="h-6 w-6 animate-spin" />
          </div>
        ) : visible.length === 0 ? (
          <div className="m-4 space-y-4 border-2 border-black bg-white p-6">
            <p className="text-sm leading-relaxed">{t(`prepDeck.empty.${category}`)}</p>
            <div className="flex flex-wrap items-center gap-2">{actions}</div>
          </div>
        ) : (
          visible.map((card, index) => (
            <ListRow
              key={card.card_id}
              title={card.question}
              subtitle={card.answer?.split('\n')[0] || t('prepDeck.card.noAnswer')}
              meta={
                <>
                  <span className="inline-flex items-center border border-black bg-paper-tint px-1 font-mono text-[10px] uppercase text-ink-soft">
                    {t(`prepDeck.confidence.${card.confidence}`)}
                  </span>
                  <span className="inline-flex items-center border border-black bg-paper-tint px-1 font-mono text-[10px] uppercase text-ink-soft">
                    {t(`prepDeck.source.${card.source}`)}
                  </span>
                </>
              }
              trailing={
                <button
                  type="button"
                  aria-label={t('common.more')}
                  onClick={(event) => {
                    event.stopPropagation();
                    setSheetCard(card);
                  }}
                  className="flex h-11 w-11 items-center justify-center active:bg-secondary"
                >
                  <MoreVertical className="h-5 w-5" />
                </button>
              }
              onClick={() => openCard(index)}
            />
          ))
        )}
      </div>

      <ActionSheet
        open={sheetCard !== null}
        onOpenChange={(open) => !open && setSheetCard(null)}
        title={sheetCard?.question ?? ''}
        items={[
          {
            id: 'edit',
            label: t('prepDeck.edit'),
            onSelect: () => {
              setFormCard(sheetCard);
              setFormOpen(true);
            },
          },
          {
            id: 'delete',
            label: t('prepDeck.delete.confirm'),
            destructive: true,
            onSelect: () => setDeleteCard(sheetCard),
          },
        ]}
      />

      <CardFormDialog
        open={formOpen}
        onOpenChange={setFormOpen}
        card={formCard}
        defaultCategory={category}
        onSaved={() => void load()}
      />

      <ConfirmDialog
        open={deleteCard !== null}
        onOpenChange={(open) => !open && setDeleteCard(null)}
        title={t('prepDeck.delete.title')}
        description={t('prepDeck.delete.description')}
        confirmLabel={t('prepDeck.delete.confirm')}
        variant="danger"
        onConfirm={handleDelete}
      />

      {studyIndex !== null && visible.length > 0 && (
        <StudyDialog
          cards={visible}
          startIndex={studyIndex}
          open
          onOpenChange={(open) => !open && setStudyIndex(null)}
          onRated={() => void load()}
        />
      )}

      {personalCard && (
        <PersonalDialog
          card={personalCard}
          open
          onOpenChange={(open) => !open && setPersonalCard(null)}
          onUpdated={() => void load()}
        />
      )}

      <ProposalReviewDialog
        open={generateOpen}
        onOpenChange={setGenerateOpen}
        proposals={proposals}
        loading={generating}
        title={t('prepDeck.generateDialog.title')}
        description={t('prepDeck.generateDialog.review')}
        onAccept={handleAcceptProposals}
      />
    </div>
  );
}
