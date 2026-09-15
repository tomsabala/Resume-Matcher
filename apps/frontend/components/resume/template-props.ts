import type { ResumeDocument } from '@/lib/types/document';

/**
 * Every resume template takes the same props: a document plus the two
 * presentation switches that are not part of the document itself.
 *
 * Templates own typography and layout; they never enumerate sections. Order is
 * `doc.sections` order, headings are `section.heading`, shape is `section.kind`
 * (dispatched through `section-kinds/SECTION_KIND_RENDERERS`) and main/sidebar
 * placement is `section.column`.
 */
export interface ResumeTemplateProps {
  doc: ResumeDocument;
  /** Render a lucide glyph next to each header contact. */
  showContactIcons?: boolean;
  /** Placeholder for an empty `header.name`, already localized by the caller. */
  fallbackName?: string;
}
