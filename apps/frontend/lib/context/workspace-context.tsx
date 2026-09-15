'use client';

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { setActiveWorkspaceId } from '@/lib/api/client';
import {
  createWorkspace as createWorkspaceRequest,
  deleteWorkspace as deleteWorkspaceRequest,
  listWorkspaces,
  updateWorkspace as updateWorkspaceRequest,
  type Workspace,
  type WorkspaceUpdate,
} from '@/lib/api/workspaces';

const STORAGE_KEY = 'rm.activeWorkspaceId';

/**
 * Browser-local state that names a document id and is therefore only valid
 * inside the workspace it was written in. Switching workspace drops it so a
 * page never resolves an id that now belongs to a different namespace.
 */
const WORKSPACE_BOUND_KEYS = ['master_resume_id', 'resume_builder_draft'];

interface WorkspaceContextValue {
  workspaces: Workspace[];
  activeWorkspace: Workspace | null;
  activeWorkspaceId: string | null;
  isLoading: boolean;
  error: string | null;
  /** Changing the active workspace bumps `revision`; pages refetch on it. */
  revision: number;
  selectWorkspace: (workspaceId: string) => void;
  createWorkspace: (name: string, contentLanguage?: string) => Promise<Workspace>;
  updateWorkspace: (workspaceId: string, payload: WorkspaceUpdate) => Promise<Workspace>;
  deleteWorkspace: (workspaceId: string) => Promise<void>;
}

const WorkspaceContext = createContext<WorkspaceContextValue | undefined>(undefined);

function storedWorkspaceId(): string | null {
  return typeof window === 'undefined' ? null : window.localStorage.getItem(STORAGE_KEY);
}

export function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  // React state starts at `null` on both sides of hydration: reading
  // localStorage in a state initializer makes the browser's first render
  // differ from the server HTML, and React reports that as a hydration
  // mismatch somewhere in this subtree (the header switcher, in practice).
  //
  // The *transport* header is a different matter - it is a module slot, not
  // rendered output, so seeding it during the first render is invisible to
  // hydration and still beats every child's fetch effect (effects run
  // child-first, so a provider effect would be too late). Without it the
  // first request of a reload would load the default workspace's resumes
  // under another workspace's name. A stale id is harmless: the backend
  // falls back to the default and `adopt` corrects the state below.
  const [activeId, setActiveId] = useState<string | null>(null);
  const seeded = useRef<boolean | null>(null);
  if (seeded.current == null) {
    seeded.current = true;
    setActiveWorkspaceId(storedWorkspaceId());
  }

  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);

  const adopt = useCallback((rows: Workspace[], preferredId: string | null) => {
    setWorkspaces(rows);
    const preferred = rows.find((row) => row.workspace_id === preferredId);
    const next = preferred ?? rows.find((row) => row.is_default) ?? rows[0] ?? null;
    const nextId = next ? next.workspace_id : null;
    setActiveId(nextId);
    // The transport reads a module-level slot rather than context so non-React
    // callers send the header too; write it synchronously because a fetch in
    // this same tick would otherwise go out unscoped.
    setActiveWorkspaceId(nextId);
    // Only a *correction* (the stored id was stale) needs a refetch; the
    // common case already loaded against this id.
    if (nextId !== preferredId) setRevision((value) => value + 1);
    return next ?? null;
  }, []);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      const stored = storedWorkspaceId();
      try {
        const rows = await listWorkspaces();
        if (cancelled) return;
        const next = adopt(rows, stored);
        if (next && typeof window !== 'undefined') {
          window.localStorage.setItem(STORAGE_KEY, next.workspace_id);
        }
        setError(null);
      } catch (loadError) {
        if (cancelled) return;
        setError(loadError instanceof Error ? loadError.message : 'Failed to load workspaces');
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [adopt]);

  const selectWorkspace = useCallback(
    (workspaceId: string) => {
      if (workspaceId === activeId) return;
      setActiveId(workspaceId);
      setActiveWorkspaceId(workspaceId);
      if (typeof window !== 'undefined') {
        window.localStorage.setItem(STORAGE_KEY, workspaceId);
        for (const key of WORKSPACE_BOUND_KEYS) window.localStorage.removeItem(key);
      }
      setRevision((value) => value + 1);
    },
    [activeId]
  );

  const createWorkspace = useCallback(
    async (name: string, contentLanguage?: string) => {
      const created = await createWorkspaceRequest({
        name,
        content_language: contentLanguage,
      });
      setWorkspaces((rows) => [...rows, created]);
      selectWorkspace(created.workspace_id);
      return created;
    },
    [selectWorkspace]
  );

  const updateWorkspace = useCallback(async (workspaceId: string, payload: WorkspaceUpdate) => {
    const updated = await updateWorkspaceRequest(workspaceId, payload);
    setWorkspaces((rows) =>
      rows.map((row) => {
        if (row.workspace_id === updated.workspace_id) return updated;
        // Promoting a default demotes every other row server-side; mirror it
        // so the UI does not show two defaults until the next reload.
        return updated.is_default && row.is_default ? { ...row, is_default: false } : row;
      })
    );
    return updated;
  }, []);

  const deleteWorkspace = useCallback(
    async (workspaceId: string) => {
      await deleteWorkspaceRequest(workspaceId);
      const remaining = workspaces.filter((row) => row.workspace_id !== workspaceId);
      setWorkspaces(remaining);
      if (workspaceId === activeId) {
        const next = remaining.find((row) => row.is_default) ?? remaining[0] ?? null;
        if (next) selectWorkspace(next.workspace_id);
      }
    },
    [activeId, selectWorkspace, workspaces]
  );

  const value = useMemo<WorkspaceContextValue>(
    () => ({
      workspaces,
      activeWorkspace: workspaces.find((row) => row.workspace_id === activeId) ?? null,
      activeWorkspaceId: activeId,
      isLoading,
      error,
      revision,
      selectWorkspace,
      createWorkspace,
      updateWorkspace,
      deleteWorkspace,
    }),
    [
      workspaces,
      activeId,
      isLoading,
      error,
      revision,
      selectWorkspace,
      createWorkspace,
      updateWorkspace,
      deleteWorkspace,
    ]
  );

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace() {
  const context = useContext(WorkspaceContext);
  if (context === undefined) {
    throw new Error('useWorkspace must be used within a WorkspaceProvider');
  }
  return context;
}
