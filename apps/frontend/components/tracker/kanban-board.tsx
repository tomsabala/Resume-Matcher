'use client';

import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  DndContext,
  DragEndEvent,
  MouseSensor,
  TouchSensor,
  KeyboardSensor,
  closestCorners,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import { sortableKeyboardCoordinates } from '@dnd-kit/sortable';
import Plus from 'lucide-react/dist/esm/icons/plus';
import Settings from 'lucide-react/dist/esm/icons/settings';
import Loader2 from 'lucide-react/dist/esm/icons/loader-2';
import ChevronLeft from 'lucide-react/dist/esm/icons/chevron-left';
import ChevronRight from 'lucide-react/dist/esm/icons/chevron-right';
import { Button } from '@/components/ui/button';
import { ActionSheet, type ActionSheetItem } from '@/components/ui/action-sheet';
import { MobileActionBar } from '@/components/common/mobile-action-bar';
import { useIsMobile } from '@/hooks/use-is-mobile';
import { useTranslations } from '@/lib/i18n';
import {
  listApplications,
  updateApplication,
  bulkUpdateStatus,
  bulkDeleteApplications,
  deleteApplication,
  APPLICATION_STATUS_ORDER,
  type Application,
  type ApplicationColumns,
  type ApplicationStatus,
} from '@/lib/api/tracker';
import { KanbanColumn } from './kanban-column';
import { BulkActionBar } from './bulk-action-bar';
import { CardDetailModal } from './card-detail-modal';
import { ManualAddApplicationDialog } from './manual-add-application-dialog';
import { planMove } from './reorder';
import { ManageColumnsDialog } from './manage-columns-dialog';
import {
  readHiddenStatuses,
  toggleHiddenStatus,
  writeHiddenStatuses,
} from '@/lib/utils/tracker-column-visibility';
import { useWorkspace } from '@/lib/context/workspace-context';

function emptyColumns(): ApplicationColumns {
  return APPLICATION_STATUS_ORDER.reduce((acc, status) => {
    acc[status] = [];
    return acc;
  }, {} as ApplicationColumns);
}

export function KanbanBoard() {
  const { t } = useTranslations();
  const { revision } = useWorkspace();
  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 4 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 250, tolerance: 8 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );

  const [columns, setColumns] = useState<ApplicationColumns>(emptyColumns);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [openCardId, setOpenCardId] = useState<string | null>(null);
  const [manualAddOpen, setManualAddOpen] = useState(false);
  const [manageOpen, setManageOpen] = useState(false);
  const [hiddenStatuses, setHiddenStatuses] = useState<Set<ApplicationStatus>>(() =>
    readHiddenStatuses()
  );

  // Mobile shows ONE stage at a time (the seven-column horizontal board is not
  // usable at 375px). The stage rail becomes the filter that picks it.
  const isMobile = useIsMobile();
  const [activeStage, setActiveStage] = useState<ApplicationStatus>('saved');
  const [cardActionsFor, setCardActionsFor] = useState<Application | null>(null);
  const [moveTargetFor, setMoveTargetFor] = useState<Application | null>(null);

  // Persist on an actual change only — an effect keyed on the state would also
  // write the just-read value straight back on mount.
  const handleToggleStatus = (status: ApplicationStatus) => {
    const next = toggleHiddenStatus(hiddenStatuses, status);
    // Refused (last visible stage): identical instance, nothing to store.
    if (next === hiddenStatuses) return;
    setHiddenStatuses(next);
    writeHiddenStatuses(next);
  };

  // Horizontal-scroll affordance: the seven stages overflow the canvas, so we
  // track whether more columns sit off-screen and surface controls + a stage
  // rail so no section is ever silently lost beyond the edge.
  const scrollRef = useRef<HTMLDivElement>(null);
  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(false);

  const load = async () => {
    try {
      const data = await listApplications();
      // Ensure all seven keys exist even if the server omits an empty one.
      setColumns({ ...emptyColumns(), ...data.columns });
      setError(null);
    } catch {
      setError(t('tracker.errors.loadFailed'));
    } finally {
      setLoading(false);
    }
  };

  // Reruns when the header switcher selects another workspace.
  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [revision]);

  const allCards: Application[] = useMemo(
    () => APPLICATION_STATUS_ORDER.flatMap((status) => columns[status]),
    [columns]
  );

  const visibleStatuses = useMemo(
    () => APPLICATION_STATUS_ORDER.filter((status) => !hiddenStatuses.has(status)),
    [hiddenStatuses]
  );

  // Hiding the active stage in "manage columns" must not leave the phone board
  // pointing at a column that no longer exists.
  const mobileStage: ApplicationStatus = visibleStatuses.includes(activeStage)
    ? activeStage
    : (visibleStatuses[0] ?? activeStage);

  // Master resume ids that back more than one card → "shared resume" badge.
  const sharedResumeIds = useMemo(() => {
    const counts = new Map<string, number>();
    for (const card of allCards) {
      if (card.master_resume_id) {
        counts.set(card.master_resume_id, (counts.get(card.master_resume_id) ?? 0) + 1);
      }
    }
    return new Set([...counts.entries()].filter(([, n]) => n > 1).map(([id]) => id));
  }, [allCards]);

  const isEmpty = allCards.length === 0;

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    // Board width is driven by the seven fixed-width columns, so we only need to
    // (re)attach when the board appears — not on every card-list change.
    const sync = () => {
      setCanScrollLeft(el.scrollLeft > 4);
      setCanScrollRight(Math.ceil(el.scrollLeft + el.clientWidth) < el.scrollWidth - 4);
    };
    sync();
    el.addEventListener('scroll', sync, { passive: true });
    window.addEventListener('resize', sync);
    return () => {
      el.removeEventListener('scroll', sync);
      window.removeEventListener('resize', sync);
    };
  }, [loading, isEmpty]);

  const scrollByColumn = (direction: 1 | -1) => {
    const el = scrollRef.current;
    if (!el) return;
    const step = el.querySelector<HTMLElement>('[data-column]')?.offsetWidth ?? el.clientWidth;
    el.scrollBy({ left: direction * step, behavior: 'smooth' });
  };

  const scrollToColumn = (status: ApplicationStatus) => {
    scrollRef.current
      ?.querySelector<HTMLElement>(`[data-column="${status}"]`)
      ?.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
  };

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over) return;
    const plan = planMove(columns, String(active.id), String(over.id));
    if (!plan) return;

    // Optimistic update. If the server rejects the move we re-load authoritative
    // state from the server rather than reverting to a captured snapshot, which
    // could be stale if another move/refresh landed in the meantime.
    setColumns(plan.next);
    updateApplication(String(active.id), { status: plan.status, position: plan.position }).catch(
      async () => {
        // Re-sync authoritative state, THEN show a generic failure message:
        // load() clears the error on success, so set it afterwards to keep it
        // visible. Never echo raw backend error text (it could leak secrets).
        await load();
        setError(t('tracker.errors.moveFailed'));
      }
    );
  };

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const nextSet = new Set(prev);
      if (nextSet.has(id)) nextSet.delete(id);
      else nextSet.add(id);
      return nextSet;
    });
  };

  const clearSelection = () => setSelectedIds(new Set());

  const handleBulkMove = async (status: ApplicationStatus) => {
    const ids = [...selectedIds];
    if (ids.length === 0) return;
    try {
      await bulkUpdateStatus(ids, status);
      clearSelection();
      await load();
    } catch {
      setError(t('tracker.errors.moveFailed'));
    }
  };

  const handleBulkDelete = async () => {
    const ids = [...selectedIds];
    if (ids.length === 0) return;
    try {
      await bulkDeleteApplications(ids);
      clearSelection();
      await load();
    } catch {
      setError(t('tracker.errors.deleteFailed'));
    }
  };

  // Mobile replacement for cross-stage drag. Mirrors handleDragEnd's ordering:
  // load() FIRST, then setError — load() clears `error` on success, so setting
  // it before the reload would wipe the message the user needs to see.
  const handleMoveCard = async (application: Application, status: ApplicationStatus) => {
    try {
      await updateApplication(application.application_id, { status, position: 0 });
      await load();
    } catch {
      await load();
      setError(t('tracker.errors.moveFailed'));
    }
  };

  const handleDeleteCard = async (application: Application) => {
    try {
      await deleteApplication(application.application_id);
      await load();
    } catch {
      await load();
      setError(t('tracker.errors.deleteFailed'));
    }
  };

  const cardActionItems: ActionSheetItem[] = cardActionsFor
    ? [
        {
          id: 'open',
          label: t('common.edit'),
          onSelect: () => setOpenCardId(cardActionsFor.application_id),
        },
        {
          id: 'move',
          label: t('tracker.bulk.moveTo'),
          // Runs before the sheet closes, so sheet 2 opens on top of the close.
          onSelect: () => setMoveTargetFor(cardActionsFor),
        },
        {
          id: 'delete',
          label: t('common.delete'),
          destructive: true,
          onSelect: () => void handleDeleteCard(cardActionsFor),
        },
      ]
    : [];

  const moveTargetItems: ActionSheetItem[] = moveTargetFor
    ? APPLICATION_STATUS_ORDER.map((status) => ({
        id: status,
        label: t(`tracker.columns.${status}`),
        disabled: status === moveTargetFor.status,
        onSelect: () => void handleMoveCard(moveTargetFor, status),
      }))
    : [];

  const showScrollControls = !isEmpty && (canScrollLeft || canScrollRight);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Header — mirrors the dashboard canvas header */}
      <div className="flex shrink-0 flex-col gap-4 border-b border-black p-4 md:flex-row md:items-center md:justify-between md:p-8">
        <div>
          <h1 className="font-serif text-3xl font-bold uppercase tracking-tight text-ink md:text-4xl">
            {t('tracker.title')}
          </h1>
          <p className="mt-2 font-mono text-xs uppercase tracking-wide text-ink-soft">
            {t('tracker.subtitle')}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 sm:gap-3">
          <Button variant="outline" onClick={() => setManageOpen(true)}>
            <Settings className="h-4 w-4" />
            {t('tracker.manage')}
          </Button>
          {showScrollControls && (
            <div className="hidden items-center lg:flex">
              <button
                type="button"
                aria-label={t('tracker.scroll.prev')}
                onClick={() => scrollByColumn(-1)}
                disabled={!canScrollLeft}
                className="flex h-11 w-11 items-center justify-center border border-black bg-background text-ink shadow-sw-xs transition-all hover:translate-x-[1px] hover:translate-y-[1px] hover:shadow-none disabled:pointer-events-none disabled:opacity-30"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
              <button
                type="button"
                aria-label={t('tracker.scroll.next')}
                onClick={() => scrollByColumn(1)}
                disabled={!canScrollRight}
                className="-ml-px flex h-11 w-11 items-center justify-center border border-black bg-background text-ink shadow-sw-xs transition-all hover:translate-x-[1px] hover:translate-y-[1px] hover:shadow-none disabled:pointer-events-none disabled:opacity-30"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          )}
          <Button onClick={() => setManualAddOpen(true)}>
            <Plus className="h-4 w-4" />
            {t('tracker.addApplication')}
          </Button>
        </div>
      </div>

      {error && (
        <div className="shrink-0 border-b border-black bg-background px-6 py-3 font-mono text-xs text-destructive md:px-8">
          {error}
        </div>
      )}

      {selectedIds.size > 0 && (
        <div className="hidden shrink-0 border-b border-black px-6 py-3 md:px-8 lg:block">
          <BulkActionBar
            selectedCount={selectedIds.size}
            onMove={handleBulkMove}
            onDelete={handleBulkDelete}
            onClear={clearSelection}
          />
        </div>
      )}

      {/* Stage rail — on mobile this is the stage FILTER (one column at a time),
          on desktop it stays the scroll-jump map of the horizontal board. It sits
          under the header on a phone and `lg:order-1` returns it to the board
          footer at desktop, where every other child keeps the default order 0. */}
      {!isEmpty && (
        <div
          role="tablist"
          aria-label={t('tracker.stageFilter')}
          className="flex shrink-0 items-center gap-2 overflow-x-auto border-b border-black bg-paper-tint px-4 py-2 md:px-8 lg:order-1 lg:gap-3 lg:border-b-0 lg:border-t"
        >
          {canScrollRight && (
            <span className="hidden shrink-0 items-center gap-1 font-mono text-[11px] font-bold uppercase tracking-wide text-primary lg:flex">
              {t('tracker.scroll.hint')}
              <ChevronRight className="h-3.5 w-3.5" />
            </span>
          )}
          {visibleStatuses.map((status) => (
            <button
              key={status}
              type="button"
              role="tab"
              aria-selected={isMobile && status === mobileStage}
              onClick={() => (isMobile ? setActiveStage(status) : scrollToColumn(status))}
              className={`relative flex shrink-0 items-center gap-1.5 border border-black px-2 py-1 font-mono text-[11px] uppercase tracking-wide shadow-sw-xs transition-all before:absolute before:-inset-[9px] before:content-[''] hover:translate-x-[1px] hover:translate-y-[1px] hover:text-primary hover:shadow-none ${
                isMobile && status === mobileStage
                  ? 'bg-black text-white'
                  : 'bg-background text-ink-soft'
              }`}
            >
              {t(`tracker.columns.${status}`)}
              <span className="text-steel-grey">{columns[status].length}</span>
            </button>
          ))}
        </div>
      )}

      {/* Board — flexes to fill the remaining canvas height; columns scroll
          horizontally as a group and vertically within each stage. */}
      <div className="flex min-h-0 flex-1 flex-col">
        {loading ? (
          <div className="flex flex-1 items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-steel-grey" />
          </div>
        ) : isEmpty ? (
          <div className="flex flex-1 flex-col items-center justify-center p-10 text-center">
            <p className="font-serif text-lg text-ink">{t('tracker.empty.title')}</p>
            <p className="mt-1 font-mono text-xs text-ink-soft">{t('tracker.empty.description')}</p>
          </div>
        ) : (
          <DndContext
            sensors={sensors}
            collisionDetection={closestCorners}
            onDragEnd={handleDragEnd}
          >
            {isMobile ? (
              // One stage at a time. `data-column` survives here: it is the
              // contract tests/manage-columns-dialog.test.tsx enumerates.
              <div className="flex min-h-0 flex-1 flex-col lg:hidden">
                <div data-column={mobileStage} className="flex min-h-0 flex-1">
                  <KanbanColumn
                    fullWidth
                    status={mobileStage}
                    applications={columns[mobileStage]}
                    selectedIds={selectedIds}
                    sharedResumeIds={sharedResumeIds}
                    onToggleSelect={toggleSelect}
                    onOpen={setOpenCardId}
                    onRequestActions={setCardActionsFor}
                  />
                </div>
              </div>
            ) : (
              <div
                ref={scrollRef}
                className="hidden min-h-0 flex-1 snap-x snap-mandatory overflow-x-auto overscroll-x-contain lg:flex"
              >
                {visibleStatuses.map((status, index) => (
                  <div
                    key={status}
                    data-column={status}
                    className={`flex ${
                      index < visibleStatuses.length - 1 ? 'border-r border-black' : ''
                    }`}
                  >
                    <KanbanColumn
                      status={status}
                      applications={columns[status]}
                      selectedIds={selectedIds}
                      sharedResumeIds={sharedResumeIds}
                      onToggleSelect={toggleSelect}
                      onOpen={setOpenCardId}
                      onRequestActions={setCardActionsFor}
                    />
                  </div>
                ))}
              </div>
            )}
          </DndContext>
        )}
      </div>

      {isMobile && selectedIds.size > 0 && (
        <MobileActionBar aboveNav className="block">
          <BulkActionBar
            selectedCount={selectedIds.size}
            onMove={handleBulkMove}
            onDelete={handleBulkDelete}
            onClear={clearSelection}
          />
        </MobileActionBar>
      )}

      <ActionSheet
        open={cardActionsFor !== null}
        onOpenChange={(open) => {
          if (!open) setCardActionsFor(null);
        }}
        title={cardActionsFor?.company?.trim() || t('tracker.card.companyUnknown')}
        items={cardActionItems}
      />

      <ActionSheet
        open={moveTargetFor !== null}
        onOpenChange={(open) => {
          if (!open) setMoveTargetFor(null);
        }}
        title={t('tracker.bulk.moveTo')}
        items={moveTargetItems}
      />

      <CardDetailModal
        applicationId={openCardId}
        open={openCardId !== null}
        onOpenChange={(open) => {
          if (!open) setOpenCardId(null);
        }}
        onUpdated={load}
      />

      <ManualAddApplicationDialog
        open={manualAddOpen}
        onOpenChange={setManualAddOpen}
        onCreated={load}
      />

      <ManageColumnsDialog
        open={manageOpen}
        onOpenChange={setManageOpen}
        hiddenStatuses={hiddenStatuses}
        onToggle={handleToggleStatus}
      />
    </div>
  );
}
