'use client';

import React, { useEffect, useState, useRef, useLayoutEffect } from 'react';
import { useRouter, useParams } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import Resume from '@/components/dashboard/resume-component';
import {
  fetchResume,
  downloadResumePdf,
  getResumePdfUrl,
  deleteResume,
  retryProcessing,
  renameResume,
  setMasterResume,
} from '@/lib/api/resume';
import { useStatusCache } from '@/lib/context/status-cache';
import {
  ArrowLeft,
  Edit,
  Download,
  Loader2,
  AlertCircle,
  Sparkles,
  Pencil,
  MessagesSquare,
  MoreVertical,
  Star,
} from 'lucide-react';
import { ActionSheet, type ActionSheetItem } from '@/components/ui/action-sheet';
import { MobileActionBar } from '@/components/common/mobile-action-bar';
import { useIsMobile } from '@/hooks/use-is-mobile';
import { EnrichmentModal } from '@/components/enrichment/enrichment-modal';
import { TexPdfPreview } from '@/components/latex/tex-pdf-preview';
import type { TexTemplateId } from '@/lib/api/tex';
import { useTranslations } from '@/lib/i18n';
import type { ResumeDocument } from '@/lib/types/document';
import {
  DEFAULT_TEMPLATE_SETTINGS,
  isTexTemplate,
  type TemplateSettings,
} from '@/lib/types/template-settings';
import { readTemplateSettings } from '@/lib/utils/template-settings-storage';
import { useLanguage } from '@/lib/context/language-context';
import { downloadBlobAsFile, openUrlInNewTab, sanitizeFilename } from '@/lib/utils/download';
import { useOperationOwner } from '@/hooks/use-operation-owner';

type ProcessingStatus = 'pending' | 'processing' | 'ready' | 'failed';

export default function ResumeViewerPage() {
  const { t } = useTranslations();
  const translationsRef = useRef(t);
  useLayoutEffect(() => {
    translationsRef.current = t;
  }, [t]);
  const { uiLanguage } = useLanguage();
  const params = useParams();
  const router = useRouter();
  const { decrementResumes, setHasMasterResume } = useStatusCache();
  const [showActionsSheet, setShowActionsSheet] = useState(false);
  const isMobile = useIsMobile();
  const [doc, setDoc] = useState<ResumeDocument | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [processingStatus, setProcessingStatus] = useState<ProcessingStatus | null>(null);
  const [isMasterResume, setIsMasterResume] = useState(false);
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [showDeleteSuccessDialog, setShowDeleteSuccessDialog] = useState(false);
  const [showDownloadSuccessDialog, setShowDownloadSuccessDialog] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [renameError, setRenameError] = useState<string | null>(null);
  const [showEnrichmentModal, setShowEnrichmentModal] = useState(false);
  const [isRetrying, setIsRetrying] = useState(false);
  const [isDownloading, setIsDownloading] = useState(false);
  const [isSettingMaster, setIsSettingMaster] = useState(false);
  const [showSetMasterDialog, setShowSetMasterDialog] = useState(false);
  const [setMasterError, setSetMasterError] = useState<string | null>(null);
  const [resumeTitle, setResumeTitle] = useState<string | null>(null);
  const renameBusyRef = useRef(false);
  const [isEditingTitle, setIsEditingTitle] = useState(false);
  const [editingTitleValue, setEditingTitleValue] = useState('');
  const [isTailoredResume, setIsTailoredResume] = useState(false);
  // The builder's template choice, read after mount: the server render has no
  // localStorage, so seeding it during render would hydrate a mismatch.
  const [templateSettings, setTemplateSettings] =
    useState<TemplateSettings>(DEFAULT_TEMPLATE_SETTINGS);
  useEffect(() => {
    setTemplateSettings(readTemplateSettings());
  }, []);
  const usesTexEngine = isTexTemplate(templateSettings.template);

  const resumeId = params?.id as string;
  const {
    begin: beginResumeLoad,
    isCurrent: isCurrentResumeLoad,
    invalidate: invalidateResumeLoad,
  } = useOperationOwner(resumeId);
  const { begin: beginRetry, isCurrent: isCurrentRetry } = useOperationOwner(resumeId);
  const { begin: beginRename, isCurrent: isCurrentRename } = useOperationOwner(resumeId);
  const { begin: beginDownload, isCurrent: isCurrentDownload } = useOperationOwner(resumeId);
  const { begin: beginDelete, isCurrent: isCurrentDelete } = useOperationOwner(resumeId);
  const { begin: beginSetMaster, isCurrent: isCurrentSetMaster } = useOperationOwner(resumeId);

  useEffect(() => {
    if (!resumeId) return;
    setShowEnrichmentModal(false);
    setIsRetrying(false);
    setIsDownloading(false);
    renameBusyRef.current = false;
    setIsEditingTitle(false);
    setEditingTitleValue('');
    setRenameError(null);
    setDownloadError(null);
    setDeleteError(null);
    setShowDeleteDialog(false);
    setShowDeleteSuccessDialog(false);
    setShowDownloadSuccessDialog(false);
    setIsSettingMaster(false);
    setShowSetMasterDialog(false);
    setSetMasterError(null);
    const token = beginResumeLoad();
    if (token === null) return;

    const loadResume = async () => {
      try {
        setLoading(true);
        setError(null);
        const data = await fetchResume(resumeId);
        if (!isCurrentResumeLoad(token)) return;

        // Get processing status
        const status = (data.raw_resume?.processing_status || 'pending') as ProcessingStatus;
        setProcessingStatus(status);

        // Capture title for editable display (always set to clear stale state)
        setResumeTitle(data.title ?? null);
        setIsTailoredResume(Boolean(data.parent_id));
        // The server owns master-ness. The cached id only covers the gap before
        // this response lands; once it is here, reconcile the cache with it so a
        // promotion in another tab or workspace cannot mislabel this resume.
        setIsMasterResume(data.is_master);
        if (data.is_master) {
          localStorage.setItem('master_resume_id', resumeId);
        } else if (localStorage.getItem('master_resume_id') === resumeId) {
          localStorage.removeItem('master_resume_id');
        }
        // The resume's own choice wins; without one, the last used in the
        // builder is the closest thing to the user's intent.
        if (data.template_settings) setTemplateSettings(data.template_settings);

        // Prioritize processed_resume if available (structured JSON)
        if (data.processed_resume) {
          setDoc(data.processed_resume);
          setError(null);
        } else if (status === 'failed') {
          setError(translationsRef.current('resumeViewer.errors.processingFailed'));
        } else if (status === 'processing') {
          setError(translationsRef.current('resumeViewer.errors.stillProcessing'));
        } else if (data.raw_resume?.content) {
          // Try to parse raw_resume content as JSON (for tailored resumes stored as JSON)
          try {
            const parsed = JSON.parse(data.raw_resume.content);
            setDoc(parsed as ResumeDocument);
          } catch {
            setError(translationsRef.current('resumeViewer.errors.notProcessedYet'));
          }
        } else {
          setError(translationsRef.current('resumeViewer.errors.noDataAvailable'));
        }
      } catch (err) {
        if (!isCurrentResumeLoad(token)) return;
        console.error('Failed to load resume:', err);
        setError(translationsRef.current('resumeViewer.errors.failedToLoad'));
      } finally {
        if (isCurrentResumeLoad(token)) setLoading(false);
      }
    };

    // Pre-fetch guess, so master-only affordances do not flicker in and out
    // while the authoritative `is_master` is still in flight.
    setIsMasterResume(localStorage.getItem('master_resume_id') === resumeId);
    loadResume();
  }, [resumeId, beginResumeLoad, isCurrentResumeLoad]);

  const handleRetryProcessing = async () => {
    if (!resumeId) return;
    const token = beginRetry();
    if (token === null) return;
    setIsRetrying(true);
    try {
      const result = await retryProcessing(resumeId);
      if (!isCurrentRetry(token)) return;
      setProcessingStatus(result.processing_status);
      if (result.processing_status === 'ready') {
        // Reload the page to show the processed resume
        window.location.reload();
      } else {
        setError(
          t(
            result.processing_status === 'failed'
              ? 'resumeViewer.errors.processingFailed'
              : 'resumeViewer.errors.stillProcessing'
          )
        );
      }
    } catch (err) {
      if (err instanceof Error && err.message.includes('status 404')) {
        if (localStorage.getItem('master_resume_id') === resumeId) {
          localStorage.removeItem('master_resume_id');
          setHasMasterResume(false);
        }
        if (!isCurrentRetry(token)) return;
        setProcessingStatus(null);
        setError(t('common.resumeDeleted'));
      } else {
        if (!isCurrentRetry(token)) return;
        console.error('Retry processing failed:', err);
        setError(t('resumeViewer.errors.processingFailed'));
      }
    } finally {
      if (isCurrentRetry(token)) setIsRetrying(false);
    }
  };

  const handleEdit = () => {
    router.push(`/builder?id=${resumeId}`);
  };

  const handleInterviewPrep = () => {
    router.push(`/builder?id=${resumeId}&tab=interview-prep`);
  };

  const handleTitleSave = async () => {
    if (renameBusyRef.current) return;
    const trimmed = editingTitleValue.trim();
    if (!trimmed || trimmed === resumeTitle) {
      setIsEditingTitle(false);
      return;
    }
    const token = beginRename();
    if (token === null) return;
    renameBusyRef.current = true;
    setIsEditingTitle(false);
    try {
      setRenameError(null);
      await renameResume(resumeId, trimmed);
      if (!isCurrentRename(token)) return;
      setResumeTitle(trimmed);
      setIsEditingTitle(false);
    } catch (err) {
      if (!isCurrentRename(token)) return;
      console.error('Failed to rename resume:', err);
      setRenameError(t('resumeViewer.errors.failedToRename'));
    } finally {
      if (isCurrentRename(token)) renameBusyRef.current = false;
    }
  };

  const handleTitleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      handleTitleSave();
    } else if (e.key === 'Escape') {
      setIsEditingTitle(false);
    }
  };

  // Reload resume data after enrichment
  const reloadDocument = async (): Promise<boolean> => {
    const token = beginResumeLoad();
    if (token === null) return false;
    try {
      const data = await fetchResume(resumeId);
      if (!isCurrentResumeLoad(token)) return false;
      if (!data.processed_resume) throw new Error('Refreshed resume has no processed data');
      setDoc(data.processed_resume);
      setError(null);
      return true;
    } catch (err) {
      if (!isCurrentResumeLoad(token)) return false;
      console.error('Failed to reload resume:', err);
      throw err;
    }
  };

  const handleEnrichmentComplete = async (): Promise<boolean> => {
    const refreshed = await reloadDocument();
    if (refreshed) setShowEnrichmentModal(false);
    return refreshed;
  };

  const handleEnrichmentClose = () => {
    invalidateResumeLoad();
    setShowEnrichmentModal(false);
  };

  const handleDownload = async () => {
    const token = beginDownload();
    if (token === null) return;
    setIsDownloading(true);
    try {
      setDownloadError(null);
      const blob = await downloadResumePdf(resumeId, templateSettings, uiLanguage);
      const filename = sanitizeFilename(resumeTitle, resumeId, 'resume');
      downloadBlobAsFile(blob, filename);
      if (!isCurrentDownload(token)) return;
      setShowDownloadSuccessDialog(true);
    } catch (err) {
      if (!isCurrentDownload(token)) return;
      console.error('Failed to download resume:', err);
      // A LaTeX template is compiled, so it has no browser-openable URL.
      if (!usesTexEngine && err instanceof TypeError && err.message.includes('Failed to fetch')) {
        const fallbackUrl = getResumePdfUrl(resumeId, templateSettings, uiLanguage);
        const didOpen = openUrlInNewTab(fallbackUrl);
        if (!didOpen) {
          setDownloadError(t('common.popupBlocked', { url: fallbackUrl }));
        }
        return;
      }
      setDownloadError(t('resumeViewer.errors.failedToDownload'));
    } finally {
      if (isCurrentDownload(token)) setIsDownloading(false);
    }
  };

  // Promotion swaps the roles: this resume becomes the source of truth and the
  // old master stays on as an ordinary resume, so nothing needs reloading here.
  const handleSetMaster = async () => {
    const token = beginSetMaster();
    if (token === null) return;
    setIsSettingMaster(true);
    try {
      setSetMasterError(null);
      await setMasterResume(resumeId);
      localStorage.setItem('master_resume_id', resumeId);
      setHasMasterResume(true);
      if (!isCurrentSetMaster(token)) return;
      setShowSetMasterDialog(false);
      setIsMasterResume(true);
    } catch (err) {
      if (!isCurrentSetMaster(token)) return;
      console.error('Failed to set master resume:', err);
      setShowSetMasterDialog(false);
      setSetMasterError(t('dashboard.manage.setMasterFailed'));
    } finally {
      if (isCurrentSetMaster(token)) setIsSettingMaster(false);
    }
  };

  const handleDeleteResume = async () => {
    const token = beginDelete();
    if (token === null) return;
    try {
      setDeleteError(null);
      await deleteResume(resumeId);
      // Update cached counters
      decrementResumes();
      if (localStorage.getItem('master_resume_id') === resumeId) {
        localStorage.removeItem('master_resume_id');
        setHasMasterResume(false);
      }
      if (!isCurrentDelete(token)) return;
      setShowDeleteDialog(false);
      setShowDeleteSuccessDialog(true);
    } catch (err) {
      if (!isCurrentDelete(token)) return;
      console.error('Failed to delete resume:', err);
      setDeleteError(t('resumeViewer.errors.failedToDelete'));
      setShowDeleteDialog(false);
    }
  };

  const handleDeleteSuccessConfirm = () => {
    setShowDeleteSuccessDialog(false);
    router.push('/dashboard');
  };

  const handleDownloadSuccessConfirm = () => {
    setShowDownloadSuccessDialog(false);
  };

  // Delete-related dialogs, shared by the failed-processing error branch and the
  // main viewer branch so the "Delete & Start Over" recovery action works in the
  // error state. Previously these lived only in the main branch, so on the error
  // path the confirm dialog never mounted and the delete request was never sent.
  // (The loading branch omits them — it has no delete affordance.)
  const deleteDialogs = (
    <>
      <ConfirmDialog
        open={showDeleteDialog}
        onOpenChange={setShowDeleteDialog}
        title={
          isMasterResume ? t('confirmations.deleteMasterResumeTitle') : t('dashboard.deleteResume')
        }
        description={
          isMasterResume
            ? t('confirmations.deleteMasterResumeDescription')
            : t('confirmations.deleteResumeFromSystemDescription')
        }
        confirmLabel={t('confirmations.deleteResumeConfirmLabel')}
        cancelLabel={t('confirmations.keepResumeCancelLabel')}
        onConfirm={handleDeleteResume}
        variant="danger"
      />

      <ConfirmDialog
        open={showDeleteSuccessDialog}
        onOpenChange={setShowDeleteSuccessDialog}
        title={t('resumeViewer.deletedTitle')}
        description={
          isMasterResume
            ? t('resumeViewer.deletedDescriptionMaster')
            : t('resumeViewer.deletedDescriptionRegular')
        }
        confirmLabel={t('resumeViewer.returnToDashboard')}
        onConfirm={handleDeleteSuccessConfirm}
        variant="success"
        showCancelButton={false}
      />

      {deleteError && (
        <ConfirmDialog
          open={!!deleteError}
          onOpenChange={() => setDeleteError(null)}
          title={t('resumeViewer.deleteFailedTitle')}
          description={deleteError}
          confirmLabel={t('common.retry')}
          cancelLabel={t('common.cancel')}
          onConfirm={handleDeleteResume}
          onCancel={() => setDeleteError(null)}
          variant="danger"
        />
      )}
    </>
  );

  if (loading) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center bg-background">
        <Loader2 className="w-10 h-10 animate-spin text-blue-700 mb-4" />
        <p className="font-mono text-sm font-bold uppercase text-blue-700">
          {t('resumeViewer.loading')}
        </p>
      </div>
    );
  }

  if (error || !doc) {
    const isProcessing = processingStatus === 'processing';
    const isFailed = processingStatus === 'failed';

    return (
      <>
        <div className="flex-1 flex flex-col items-center justify-center bg-background p-4">
          <div
            className={`border p-6 text-center max-w-md shadow-sw-default ${
              isProcessing
                ? 'bg-blue-50 border-blue-200'
                : isFailed
                  ? 'bg-orange-50 border-orange-200'
                  : 'bg-red-50 border-red-200'
            }`}
          >
            <div className="flex justify-center mb-4">
              {isProcessing ? (
                <Loader2 className="w-8 h-8 animate-spin text-blue-700" />
              ) : isFailed ? (
                <AlertCircle className="w-8 h-8 text-orange-600" />
              ) : (
                <AlertCircle className="w-8 h-8 text-red-600" />
              )}
            </div>
            <p
              className={`font-bold mb-4 ${
                isProcessing ? 'text-blue-700' : isFailed ? 'text-orange-700' : 'text-red-700'
              }`}
            >
              {error || t('resumeViewer.resumeNotFound')}
            </p>
            <div className="flex flex-col gap-2">
              {isFailed && (
                <>
                  <Button onClick={handleRetryProcessing} disabled={isRetrying}>
                    {isRetrying ? (
                      <>
                        <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                        {t('common.processing')}
                      </>
                    ) : (
                      t('resumeViewer.retryProcessing')
                    )}
                  </Button>
                  <Button variant="destructive" onClick={() => setShowDeleteDialog(true)}>
                    {t('resumeViewer.deleteAndStartOver')}
                  </Button>
                </>
              )}
              <Button variant="outline" onClick={() => router.push('/dashboard')}>
                {t('resumeViewer.returnToDashboard')}
              </Button>
            </div>
          </div>
        </div>
        {deleteDialogs}
      </>
    );
  }

  const mobileActionItems: ActionSheetItem[] = [
    ...(isMasterResume
      ? [
          {
            id: 'enhance',
            label: t('resumeViewer.enhanceResume'),
            onSelect: () => setShowEnrichmentModal(true),
          },
        ]
      : []),
    ...(!isMasterResume && processingStatus === 'ready'
      ? [
          {
            id: 'set-master',
            label: t('resumeViewer.setMaster'),
            disabled: isSettingMaster,
            onSelect: () => setShowSetMasterDialog(true),
          },
        ]
      : []),
    { id: 'edit', label: t('dashboard.editResume'), onSelect: handleEdit },
    ...(isTailoredResume
      ? [
          {
            id: 'interview-prep',
            label: t('interviewPrep.title'),
            onSelect: handleInterviewPrep,
          },
        ]
      : []),
    ...(!isMasterResume
      ? [
          {
            id: 'rename',
            label: t('dashboard.manage.rename'),
            onSelect: () => {
              setEditingTitleValue(resumeTitle || '');
              setIsEditingTitle(true);
            },
          },
        ]
      : []),
    {
      id: 'delete',
      label: isMasterResume
        ? t('confirmations.deleteMasterResumeTitle')
        : t('dashboard.deleteResume'),
      destructive: true,
      onSelect: () => setShowDeleteDialog(true),
    },
  ];

  return (
    <div className="flex flex-1 flex-col bg-background">
      <div className="flex-1 py-6 px-4 md:py-12 md:px-8">
        <div className="max-w-7xl mx-auto">
          {/* Header Actions — every one of these lives in the mobile action sheet below. */}
          <div className="mb-8 hidden lg:flex flex-col md:flex-row justify-between items-start md:items-center gap-4 no-print">
            <Button variant="outline" onClick={() => router.push('/dashboard')}>
              <ArrowLeft className="w-4 h-4" />
              {t('nav.backToDashboard')}
            </Button>

            <div className="flex flex-wrap gap-2 w-full md:w-auto md:gap-3">
              {isMasterResume && (
                <Button onClick={() => setShowEnrichmentModal(true)} className="gap-2">
                  <Sparkles className="w-4 h-4" />
                  {t('resumeViewer.enhanceResume')}
                </Button>
              )}
              {!isMasterResume && processingStatus === 'ready' && (
                <Button
                  variant="outline"
                  onClick={() => setShowSetMasterDialog(true)}
                  disabled={isSettingMaster}
                >
                  <Star className="w-4 h-4" />
                  {t('resumeViewer.setMaster')}
                </Button>
              )}
              <Button variant="outline" onClick={handleEdit}>
                <Edit className="w-4 h-4" />
                {t('dashboard.editResume')}
              </Button>
              {isTailoredResume && (
                <Button variant="outline" onClick={handleInterviewPrep}>
                  <MessagesSquare className="w-4 h-4" />
                  {t('interviewPrep.title')}
                </Button>
              )}
              <Button variant="success" onClick={handleDownload} disabled={isDownloading}>
                <Download className="w-4 h-4" />
                {isDownloading ? t('common.generating') : t('resumeViewer.downloadResume')}
              </Button>
            </div>
          </div>

          {/* Mobile: one ⋯ trigger stands in for the whole desktop action row. */}
          {isMobile && (
            <div className="mb-4 flex justify-end lg:hidden no-print">
              <button
                type="button"
                onClick={() => setShowActionsSheet(true)}
                aria-label={t('common.more')}
                className="flex h-11 w-11 items-center justify-center border border-black bg-background active:bg-secondary"
              >
                <MoreVertical className="h-5 w-5" />
              </button>
            </div>
          )}

          {/* Editable Title (tailored resumes only) */}
          {!isMasterResume && (
            <div className="mb-6 no-print">
              {isEditingTitle ? (
                <input
                  type="text"
                  value={editingTitleValue}
                  onChange={(e) => setEditingTitleValue(e.target.value)}
                  onBlur={handleTitleSave}
                  onKeyDown={handleTitleKeyDown}
                  autoFocus
                  maxLength={80}
                  placeholder={t('resumeViewer.titlePlaceholder')}
                  className="font-serif text-2xl font-bold border-b-2 border-black bg-transparent outline-none w-full max-w-xl px-0 py-1"
                />
              ) : (
                <button
                  onClick={() => {
                    setEditingTitleValue(resumeTitle || '');
                    setIsEditingTitle(true);
                  }}
                  className="group flex items-center gap-2 cursor-pointer bg-transparent border-none p-0"
                >
                  <h2
                    className={`font-serif text-2xl font-bold border-b-2 border-transparent group-hover:border-black transition-colors ${!resumeTitle ? 'text-steel-grey' : ''}`}
                  >
                    {resumeTitle || t('resumeViewer.titlePlaceholder')}
                  </h2>
                  <Pencil
                    className={`w-4 h-4 transition-opacity ${resumeTitle ? 'opacity-60 lg:opacity-0 lg:group-hover:opacity-60' : 'opacity-40 group-hover:opacity-60'}`}
                  />
                </button>
              )}
            </div>
          )}

          {/* Resume Viewer — the renderer the selected template belongs to. */}
          <div className="flex justify-center pb-4">
            {usesTexEngine ? (
              <div className="w-full max-w-[250mm] h-[70dvh] sm:h-[297mm] border-2 border-black bg-white shadow-sw-lg">
                <TexPdfPreview
                  resumeId={resumeId}
                  template={templateSettings.template as TexTemplateId}
                  settings={templateSettings}
                  revision={0}
                />
              </div>
            ) : (
              <div className="resume-print w-full max-w-[250mm] shadow-sw-lg border-2 border-black bg-white">
                <Resume
                  doc={doc}
                  settings={templateSettings}
                  translate={t}
                  fallbackName={t('resume.defaults.name')}
                />
              </div>
            )}
          </div>

          <div className="hidden lg:flex justify-end pt-4 no-print">
            <Button variant="destructive" onClick={() => setShowDeleteDialog(true)}>
              {isMasterResume
                ? t('confirmations.deleteMasterResumeTitle')
                : t('dashboard.deleteResume')}
            </Button>
          </div>
        </div>
      </div>

      {isMobile && (
        <>
          <MobileActionBar className="no-print">
            <Button
              variant="success"
              onClick={handleDownload}
              disabled={isDownloading}
              className="w-full"
            >
              <Download className="w-4 h-4" />
              {isDownloading ? t('common.generating') : t('resumeViewer.downloadResume')}
            </Button>
          </MobileActionBar>

          <ActionSheet
            open={showActionsSheet}
            onOpenChange={setShowActionsSheet}
            title={
              resumeTitle || t(isMasterResume ? 'dashboard.masterResume' : 'dashboard.baseResume')
            }
            items={mobileActionItems}
          />
        </>
      )}

      {deleteDialogs}

      <ConfirmDialog
        open={downloadError !== null}
        onOpenChange={(open) => !open && setDownloadError(null)}
        title={t('resumeViewer.downloadFailedTitle')}
        description={downloadError ?? ''}
        confirmLabel={t('common.retry')}
        cancelLabel={t('common.cancel')}
        onConfirm={handleDownload}
        onCancel={() => setDownloadError(null)}
        variant="danger"
      />

      <ConfirmDialog
        open={renameError !== null}
        onOpenChange={(open) => !open && setRenameError(null)}
        title={t('resumeViewer.renameFailedTitle')}
        description={renameError ?? ''}
        confirmLabel={t('common.retry')}
        cancelLabel={t('common.cancel')}
        onConfirm={handleTitleSave}
        onCancel={() => setRenameError(null)}
        variant="danger"
      />

      <ConfirmDialog
        open={showSetMasterDialog}
        onOpenChange={setShowSetMasterDialog}
        title={t('confirmations.setMasterTitle', {
          title:
            resumeTitle ||
            t(isTailoredResume ? 'dashboard.tailoredResume' : 'dashboard.baseResume'),
        })}
        description={t('confirmations.setMasterDescription')}
        confirmLabel={t('resumeViewer.setMaster')}
        cancelLabel={t('common.cancel')}
        confirmDisabled={isSettingMaster}
        closeOnConfirm={false}
        onConfirm={handleSetMaster}
      />

      <ConfirmDialog
        open={setMasterError !== null}
        onOpenChange={(open) => !open && setSetMasterError(null)}
        title={t('common.error')}
        description={setMasterError ?? ''}
        confirmLabel={t('common.retry')}
        cancelLabel={t('common.cancel')}
        onConfirm={handleSetMaster}
        onCancel={() => setSetMasterError(null)}
        variant="danger"
      />

      <ConfirmDialog
        open={showDownloadSuccessDialog}
        onOpenChange={setShowDownloadSuccessDialog}
        title={t('common.success')}
        description={t('builder.alerts.downloadSuccess')}
        confirmLabel={t('common.ok')}
        onConfirm={handleDownloadSuccessConfirm}
        variant="success"
        showCancelButton={false}
      />

      {/* Enrichment Modal - Only for master resume */}
      {isMasterResume && (
        <EnrichmentModal
          resumeId={resumeId}
          isOpen={showEnrichmentModal}
          onClose={handleEnrichmentClose}
          onComplete={handleEnrichmentComplete}
        />
      )}
    </div>
  );
}
