'use client';

import { useEffect, useRef, useState } from 'react';
import ChevronDown from 'lucide-react/dist/esm/icons/chevron-down';
import Pencil from 'lucide-react/dist/esm/icons/pencil';
import Plus from 'lucide-react/dist/esm/icons/plus';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { useTranslations } from '@/lib/i18n';
import { useWorkspace } from '@/lib/context/workspace-context';
import { WorkspaceManageDialog } from '@/components/common/workspace-manage-dialog';
import type { Workspace } from '@/lib/api/workspaces';

/**
 * Workspace switcher for the app header.
 *
 * Swiss dropdown: mono uppercase rows, 1px black borders, hard shadow, no
 * rounding and no transitions on the surface itself.
 */
export function WorkspaceSwitcher() {
  const { t } = useTranslations();
  const { workspaces, activeWorkspace, isLoading, selectWorkspace, createWorkspace } =
    useWorkspace();
  const [isOpen, setIsOpen] = useState(false);
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [name, setName] = useState('');
  const [createError, setCreateError] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [managed, setManaged] = useState<Workspace | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isOpen) return;
    const handlePointerDown = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setIsOpen(false);
    };
    document.addEventListener('mousedown', handlePointerDown);
    return () => document.removeEventListener('mousedown', handlePointerDown);
  }, [isOpen]);

  const submit = async () => {
    const trimmed = name.trim();
    if (!trimmed) {
      setCreateError(t('workspaces.nameRequired'));
      return;
    }
    setIsCreating(true);
    try {
      await createWorkspace(trimmed);
      setName('');
      setCreateError(null);
      setIsDialogOpen(false);
    } catch (error) {
      setCreateError(error instanceof Error ? error.message : t('workspaces.createFailed'));
    } finally {
      setIsCreating(false);
    }
  };

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        // Never `disabled={isLoading}`: the server renders this button before
        // the workspace list exists and the browser may hydrate it after the
        // list has landed, so a load-derived attribute is a hydration
        // mismatch by construction. The label carries the loading state, and
        // an always-clickable trigger still offers "New workspace" when the
        // list request failed.
        aria-busy={isLoading}
        aria-haspopup="menu"
        aria-expanded={isOpen}
        aria-label={t('workspaces.switcherLabel')}
        className="flex items-center gap-2 border border-black bg-white px-3 py-2 font-mono text-xs uppercase tracking-wider text-black shadow-sw-sm rounded-none"
      >
        <span className="max-w-[14rem] truncate font-bold">
          {activeWorkspace?.name ?? t('workspaces.loading')}
        </span>
        <ChevronDown className="h-3 w-3 shrink-0" />
      </button>

      {isOpen && (
        <div
          role="menu"
          aria-label={t('workspaces.switcherLabel')}
          className="absolute right-0 top-full z-50 mt-1 min-w-[16rem] border border-black bg-white shadow-sw-default rounded-none"
        >
          {workspaces.map((workspace, index) => (
            <div
              key={workspace.workspace_id}
              className={`flex items-stretch ${index > 0 ? '-mt-[1px]' : ''}`}
            >
              <button
                role="menuitemradio"
                aria-checked={workspace.workspace_id === activeWorkspace?.workspace_id}
                onClick={() => {
                  selectWorkspace(workspace.workspace_id);
                  setIsOpen(false);
                }}
                className={`flex min-w-0 flex-1 items-center justify-between gap-3 border border-black px-3 py-2 text-left font-mono text-sm uppercase tracking-wider ${
                  workspace.workspace_id === activeWorkspace?.workspace_id
                    ? 'bg-green-700 text-white'
                    : 'bg-white text-black hover:bg-paper-tint'
                }`}
              >
                <span className="truncate">{workspace.name}</span>
                <span className="shrink-0 text-xs opacity-80">{workspace.content_language}</span>
              </button>
              <button
                type="button"
                role="menuitem"
                aria-label={t('workspaces.manageLabel', { name: workspace.name })}
                title={t('workspaces.manageLabel', { name: workspace.name })}
                onClick={() => {
                  setIsOpen(false);
                  setManaged(workspace);
                }}
                className="-ml-[1px] flex shrink-0 items-center justify-center border border-black bg-white px-3 text-black hover:bg-paper-tint"
              >
                <Pencil className="h-3 w-3" />
              </button>
            </div>
          ))}
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setIsOpen(false);
              setIsDialogOpen(true);
            }}
            className="-mt-[1px] flex w-full items-center gap-2 border border-black bg-white px-3 py-2 text-left font-mono text-sm uppercase tracking-wider text-black hover:bg-paper-tint"
          >
            <Plus className="h-3 w-3" />
            {t('workspaces.new')}
          </button>
        </div>
      )}

      <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
        <DialogContent className="max-w-md border-2 border-black shadow-[4px_4px_0px_0px_#000000]">
          <DialogHeader>
            <DialogTitle>{t('workspaces.newTitle')}</DialogTitle>
            <DialogDescription>{t('workspaces.newDescription')}</DialogDescription>
          </DialogHeader>
          <Input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder={t('workspaces.namePlaceholder')}
            aria-label={t('workspaces.nameLabel')}
            onKeyDown={(event) => {
              if (event.key === 'Enter') void submit();
            }}
          />
          {createError && (
            <p className="font-mono text-xs uppercase tracking-wider text-red-600">{createError}</p>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsDialogOpen(false)}>
              {t('common.cancel')}
            </Button>
            <Button onClick={() => void submit()} disabled={isCreating}>
              {t('workspaces.create')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <WorkspaceManageDialog workspace={managed} onClose={() => setManaged(null)} />
    </div>
  );
}
