import { AppHeader } from '@/components/common/app-header';
import { ResumePreviewProvider } from '@/components/common/resume_previewer_context';
import { StatusCacheProvider } from '@/lib/context/status-cache';
import { LanguageProvider } from '@/lib/context/language-context';
import { WorkspaceProvider } from '@/lib/context/workspace-context';
import { LocalizedErrorBoundary } from '@/components/common/error-boundary';

export default function DefaultLayout({ children }: { children: React.ReactNode }) {
  return (
    <StatusCacheProvider>
      {/* Workspaces sit outside LanguageProvider: a workspace carries its own
          content_language, so it must be able to seed the language layer. */}
      <WorkspaceProvider>
        <LanguageProvider>
          <ResumePreviewProvider>
            <LocalizedErrorBoundary>
              <AppHeader />
              <main className="min-h-screen flex flex-col">{children}</main>
            </LocalizedErrorBoundary>
          </ResumePreviewProvider>
        </LanguageProvider>
      </WorkspaceProvider>
    </StatusCacheProvider>
  );
}
