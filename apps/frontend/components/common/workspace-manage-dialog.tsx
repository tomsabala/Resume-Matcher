'use client';

import { useEffect, useState } from 'react';
import Trash2 from 'lucide-react/dist/esm/icons/trash-2';
import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { locales, localeNames } from '@/i18n/config';
import { useTranslations } from '@/lib/i18n';
import { useWorkspace } from '@/lib/context/workspace-context';
import type { Workspace } from '@/lib/api/workspaces';

interface WorkspaceManageDialogProps {
  /** The workspace being edited; `null` keeps the dialog closed. */
  workspace: Workspace | null;
  onClose: () => void;
}

/**
 * Rename a workspace, change the language its content is written in, promote
 * it to default, or delete it with everything scoped to it.
 *
 * Deleting the default workspace or the only workspace is refused by the
 * server (409); the message is shown here rather than translated locally, so
 * the rule has one owner.
 */
export function WorkspaceManageDialog({ workspace, onClose }: WorkspaceManageDialogProps) {
  const { t } = useTranslations();
  const { updateWorkspace, deleteWorkspace } = useWorkspace();
  const [name, setName] = useState('');
  const [language, setLanguage] = useState('en');
  const [error, setError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  // Re-seed the form whenever a different row opens it: the dialog outlives
  // any one workspace.
  useEffect(() => {
    if (!workspace) return;
    setName(workspace.name);
    setLanguage(workspace.content_language);
    setError(null);
  }, [workspace]);

  if (!workspace) return null;

  const save = async (extra?: { is_default?: boolean }) => {
    const trimmed = name.trim();
    if (!trimmed) {
      setError(t('workspaces.nameRequired'));
      return;
    }
    setIsSaving(true);
    try {
      await updateWorkspace(workspace.workspace_id, {
        name: trimmed,
        content_language: language,
        ...extra,
      });
      onClose();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : t('workspaces.updateFailed'));
    } finally {
      setIsSaving(false);
    }
  };

  const remove = async () => {
    setIsDeleting(true);
    try {
      await deleteWorkspace(workspace.workspace_id);
      setConfirmDelete(false);
      onClose();
    } catch (deleteError) {
      setConfirmDelete(false);
      setError(deleteError instanceof Error ? deleteError.message : t('workspaces.deleteFailed'));
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <>
      <Dialog open onOpenChange={(open) => !open && onClose()}>
        <DialogContent className="max-w-md border-2 border-black shadow-[4px_4px_0px_0px_#000000]">
          <DialogHeader>
            <DialogTitle>{t('workspaces.manageTitle')}</DialogTitle>
            <DialogDescription>{t('workspaces.manageDescription')}</DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="space-y-1">
              <label
                htmlFor="workspace-name"
                className="font-mono text-xs font-bold uppercase tracking-wider"
              >
                {t('workspaces.nameLabel')}
              </label>
              <Input
                id="workspace-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder={t('workspaces.namePlaceholder')}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') void save();
                }}
              />
            </div>

            <div className="space-y-1">
              <label
                htmlFor="workspace-language"
                className="font-mono text-xs font-bold uppercase tracking-wider"
              >
                {t('workspaces.languageLabel')}
              </label>
              <select
                id="workspace-language"
                value={language}
                onChange={(event) => setLanguage(event.target.value)}
                className="w-full border border-black bg-white px-3 py-2 font-mono text-sm rounded-none focus:outline-none focus:ring-0"
              >
                {locales.map((code) => (
                  <option key={code} value={code}>
                    {localeNames[code]}
                  </option>
                ))}
              </select>
            </div>

            {workspace.is_default ? (
              <p className="font-mono text-xs uppercase tracking-wider text-green-700">
                {t('workspaces.isDefault')}
              </p>
            ) : (
              <Button
                variant="outline"
                size="sm"
                disabled={isSaving}
                onClick={() => void save({ is_default: true })}
              >
                {t('workspaces.makeDefault')}
              </Button>
            )}

            {error && (
              <p role="alert" className="font-mono text-xs uppercase tracking-wider text-red-600">
                {error}
              </p>
            )}
          </div>

          {/* Below `sm` the destructive action must not sit in a thumb-height row next to
              Cancel, so it gets its own block above the footer. */}
          <div className="border-t border-black pt-4 sm:hidden">
            <Button
              variant="destructive"
              onClick={() => setConfirmDelete(true)}
              disabled={isDeleting}
              className="w-full sm:w-auto"
            >
              <Trash2 className="h-4 w-4" />
              {t('common.delete')}
            </Button>
          </div>

          <DialogFooter>
            <Button
              variant="destructive"
              onClick={() => setConfirmDelete(true)}
              disabled={isDeleting}
              className="hidden sm:inline-flex"
            >
              <Trash2 className="h-4 w-4" />
              {t('common.delete')}
            </Button>
            <Button variant="outline" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <Button onClick={() => void save()} disabled={isSaving}>
              {t('common.save')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        title={t('workspaces.deleteTitle')}
        description={t('workspaces.deleteDescription', { name: workspace.name })}
        confirmLabel={t('common.delete')}
        cancelLabel={t('common.cancel')}
        confirmDisabled={isDeleting}
        onConfirm={() => void remove()}
        variant="danger"
      />
    </>
  );
}
