import {
  SCHEMA_VERSION,
  type ResumeDocument,
  type Section,
  type SectionKind,
} from '@/lib/types/document';
import { normalizeResumeForSave } from '@/lib/utils/resume-normalization';
import {
  createInitialResumeWizardState,
  type ResumeWizardHistoryEntry,
  type ResumeWizardSection,
  type ResumeWizardState,
  type ResumeWizardStep,
} from '@/lib/api/resume-wizard';

export const RESUME_WIZARD_DRAFT_STORAGE_KEY = 'resume_wizard_draft';
export const RESUME_WIZARD_DRAFT_SCHEMA_VERSION = 2;

const MAX_QUESTIONS = 15;
const STEPS: ResumeWizardStep[] = ['intro', 'question', 'review', 'complete'];
const SECTION_KINDS: SectionKind[] = ['text', 'entries', 'tags', 'groups'];

interface ResumeWizardDraftEnvelope {
  schemaVersion: typeof RESUME_WIZARD_DRAFT_SCHEMA_VERSION;
  state: ResumeWizardState;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function stringValue(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback;
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is string => typeof item === 'string')
    .map((item) => item.trim())
    .filter(Boolean);
}

/**
 * The wizard addresses one section at a time by key, plus the three fixed
 * bookends. Anything else in a persisted draft is a discriminator this build
 * cannot act on.
 */
function isWizardSection(value: unknown): value is ResumeWizardSection {
  if (typeof value !== 'string') return false;
  return (
    value === 'intro' || value === 'contact' || value === 'review' || /^section:.+/.test(value)
  );
}

function integerInRange(
  value: unknown,
  fallback: number,
  minimum: number,
  maximum: number
): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) return fallback;
  return Math.min(maximum, Math.max(minimum, Math.trunc(value)));
}

/**
 * Rebuild a section's identity from untrusted JSON.
 *
 * Only identity is settled here — content (entries, bullets, tags, groups,
 * contacts) is handed to `normalizeResumeForSave`, which is the one place that
 * knows how to clean each kind. A section with an unusable `kind` is dropped:
 * no renderer or form could dispatch on it.
 */
function normalizeSection(value: unknown, index: number): Section | null {
  if (!isRecord(value)) return null;
  if (!SECTION_KINDS.includes(value.kind as SectionKind)) return null;

  const key = stringValue(value.key).trim() || `section_${index + 1}`;
  return {
    id: stringValue(value.id).trim() || key,
    key,
    heading: stringValue(value.heading),
    headingI18nKey: typeof value.headingI18nKey === 'string' ? value.headingI18nKey : null,
    kind: value.kind as SectionKind,
    visible: value.visible !== false,
    column: value.column === 'side' ? 'side' : 'main',
    text: stringValue(value.text),
    entries: (value.entries ?? []) as Section['entries'],
    tags: stringList(value.tags),
    groups: (value.groups ?? []) as Section['groups'],
  };
}

function normalizeResumeDocument(value: unknown, fallback: ResumeDocument): ResumeDocument {
  if (!isRecord(value)) return fallback;
  const header = isRecord(value.header) ? value.header : {};
  const sections = (Array.isArray(value.sections) ? value.sections : [])
    .map(normalizeSection)
    .filter((section): section is Section => section !== null);

  return normalizeResumeForSave({
    schemaVersion: SCHEMA_VERSION,
    header: {
      name: stringValue(header.name),
      headline: stringValue(header.headline),
      contacts: (header.contacts ?? []) as ResumeDocument['header']['contacts'],
    },
    sections,
  });
}

function normalizeHistory(
  value: unknown,
  fallbackResume: ResumeDocument
): ResumeWizardHistoryEntry[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((entry) => {
    if (!isRecord(entry)) return [];
    if (
      typeof entry.question !== 'string' ||
      typeof entry.answer !== 'string' ||
      !isWizardSection(entry.section) ||
      !isRecord(entry.resume_data_before)
    ) {
      return [];
    }
    return [
      {
        question: entry.question,
        answer: entry.answer,
        section: entry.section,
        resume_data_before: normalizeResumeDocument(entry.resume_data_before, fallbackResume),
      },
    ];
  });
}

function normalizeState(value: unknown): ResumeWizardState | null {
  if (!isRecord(value)) return null;
  const initial = createInitialResumeWizardState();
  // A completed wizard is never persisted by the current writer. Restoring a
  // hand-written/stale complete state would produce a page with no created id
  // and no valid action, so treat it as corrupt instead of trapping the user.
  if (value.step === 'complete') return null;
  const question = isRecord(value.current_question) ? value.current_question : {};
  const section = isWizardSection(question.section)
    ? question.section
    : initial.current_question.section;
  const resumeData = normalizeResumeDocument(value.resume_data, initial.resume_data);
  const askedCount = integerInRange(value.asked_count, 0, 0, MAX_QUESTIONS);
  const total = isRecord(value.progress)
    ? integerInRange(value.progress.total, initial.progress.total, 1, MAX_QUESTIONS)
    : initial.progress.total;

  return {
    step: STEPS.includes(value.step as ResumeWizardStep)
      ? (value.step as ResumeWizardStep)
      : initial.step,
    resume_data: resumeData,
    current_question: {
      text:
        typeof question.text === 'string' && question.text.trim()
          ? question.text
          : initial.current_question.text,
      section,
    },
    history: normalizeHistory(value.history, initial.resume_data),
    asked_count: askedCount,
    inferred_skills: stringList(value.inferred_skills),
    is_complete: value.is_complete === true,
    progress: {
      current: isRecord(value.progress)
        ? integerInRange(
            value.progress.current,
            Math.min(askedCount, total),
            0,
            Math.min(askedCount, total)
          )
        : Math.min(askedCount, total),
      total,
    },
    warnings: stringList(value.warnings),
  };
}

export function readResumeWizardDraft(): ResumeWizardState | null {
  try {
    const raw = localStorage.getItem(RESUME_WIZARD_DRAFT_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as unknown;
    if (!isRecord(parsed)) return null;
    if ('schemaVersion' in parsed || 'state' in parsed) {
      if (parsed.schemaVersion !== RESUME_WIZARD_DRAFT_SCHEMA_VERSION) return null;
      return normalizeState(parsed.state);
    }
    return normalizeState(parsed);
  } catch {
    return null;
  }
}

export function writeResumeWizardDraft(state: ResumeWizardState): boolean {
  const envelope: ResumeWizardDraftEnvelope = {
    schemaVersion: RESUME_WIZARD_DRAFT_SCHEMA_VERSION,
    state,
  };
  try {
    localStorage.setItem(RESUME_WIZARD_DRAFT_STORAGE_KEY, JSON.stringify(envelope));
    return true;
  } catch {
    return false;
  }
}

export function clearResumeWizardDraft(): boolean {
  try {
    localStorage.removeItem(RESUME_WIZARD_DRAFT_STORAGE_KEY);
    return true;
  } catch {
    return false;
  }
}

/** A failed remove can leave an already finalized review draft behind. */
export function writeResumeWizardCompletion(resumeId: string): boolean {
  try {
    localStorage.setItem(
      RESUME_WIZARD_DRAFT_STORAGE_KEY,
      JSON.stringify({
        schemaVersion: RESUME_WIZARD_DRAFT_SCHEMA_VERSION,
        completedResumeId: resumeId,
      })
    );
    return true;
  } catch {
    return false;
  }
}

export function readResumeWizardCompletion(): string | null {
  try {
    const value: unknown = JSON.parse(
      localStorage.getItem(RESUME_WIZARD_DRAFT_STORAGE_KEY) ?? 'null'
    );
    return isRecord(value) &&
      value.schemaVersion === RESUME_WIZARD_DRAFT_SCHEMA_VERSION &&
      typeof value.completedResumeId === 'string' &&
      value.completedResumeId.trim()
      ? value.completedResumeId
      : null;
  } catch {
    return null;
  }
}

/** Retire this acknowledged resume without removing a newer draft or receipt. */
export function clearResumeWizardCompletion(resumeId: string): boolean {
  try {
    const value: unknown = JSON.parse(
      localStorage.getItem(RESUME_WIZARD_DRAFT_STORAGE_KEY) ?? 'null'
    );
    if (
      isRecord(value) &&
      value.schemaVersion === RESUME_WIZARD_DRAFT_SCHEMA_VERSION &&
      !('state' in value) &&
      value.completedResumeId === resumeId
    ) {
      localStorage.removeItem(RESUME_WIZARD_DRAFT_STORAGE_KEY);
    }
    return true;
  } catch {
    return false;
  }
}
