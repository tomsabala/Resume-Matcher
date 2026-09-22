import { AppHeader } from '@/components/common/app-header';
import { BottomNav } from '@/components/common/bottom-nav';
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
              <div className="flex min-h-[100dvh] flex-col">
                <AppHeader />
                <main className="flex min-h-0 flex-1 flex-col">{children}</main>
                <BottomNav />
              </div>
            </LocalizedErrorBoundary>
          </ResumePreviewProvider>
        </LanguageProvider>
      </WorkspaceProvider>
    </StatusCacheProvider>
  );
}
