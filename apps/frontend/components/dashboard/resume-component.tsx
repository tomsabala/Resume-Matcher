import React from 'react';
import {
  ResumeSingleColumn,
  ResumeTwoColumn,
  ResumeModern,
  ResumeModernTwoColumn,
  ResumeLatex,
  ResumeClean,
  ResumeVivid,
} from '@/components/resume';
import type { ResumeTemplateProps } from '@/components/resume/template-props';
import {
  type TemplateSettings,
  type TemplateType,
  DEFAULT_TEMPLATE_SETTINGS,
  settingsToCssVars,
} from '@/lib/types/template-settings';
import type { ResumeDocument } from '@/lib/types/document';
import { sectionHeading } from '@/lib/utils/section-helpers';
import baseStyles from '@/components/resume/styles/_base.module.css';

const TEMPLATE_COMPONENTS: Record<TemplateType, React.FC<ResumeTemplateProps>> = {
  'swiss-single': ResumeSingleColumn,
  'swiss-two-column': ResumeTwoColumn,
  modern: ResumeModern,
  'modern-two-column': ResumeModernTwoColumn,
  latex: ResumeLatex,
  clean: ResumeClean,
  vivid: ResumeVivid,
};

interface ResumeProps {
  doc: ResumeDocument;
  template?: TemplateType;
  settings?: TemplateSettings;
  /**
   * Resolves `resume.sections.*` keys. Headings projected from the v1
   * built-ins carry a `headingI18nKey`, and `sectionHeading` translates one
   * only while the user has not renamed it. Without this prop every heading
   * renders verbatim.
   */
  translate?: (key: string) => string;
  /** Placeholder for an empty `header.name`, already localized by the caller. */
  fallbackName?: string;
  /**
   * Content locale ("zh" | "ja" | "ko" | ...). Orders the CJK font fallback
   * stack so a shared codepoint resolves to the right regional face.
   */
  locale?: string;
}

/**
 * Resume Component
 *
 * Applies the template settings as CSS custom properties and delegates
 * rendering to the selected template. Templates receive the document as-is:
 * sections, their headings, their order and their shapes are data.
 */
const Resume: React.FC<ResumeProps> = ({
  doc,
  template = 'swiss-single',
  settings,
  translate,
  fallbackName,
  locale,
}) => {
  const mergedSettings: TemplateSettings = {
    ...DEFAULT_TEMPLATE_SETTINGS,
    ...settings,
    margins: { ...DEFAULT_TEMPLATE_SETTINGS.margins, ...settings?.margins },
    spacing: { ...DEFAULT_TEMPLATE_SETTINGS.spacing, ...settings?.spacing },
    fontSize: { ...DEFAULT_TEMPLATE_SETTINGS.fontSize, ...settings?.fontSize },
  };

  // If template is provided as prop but not in settings, use the prop
  if (template && !settings?.template) {
    mergedSettings.template = template;
  }

  const cssVars = settingsToCssVars(mergedSettings, locale);
  const Template = TEMPLATE_COMPONENTS[mergedSettings.template] ?? ResumeSingleColumn;

  return (
    <div
      className={`${baseStyles['resume-body']} bg-white text-black w-full mx-auto resume-template-${mergedSettings.template}`}
      style={cssVars}
    >
      <Template
        doc={translate ? localizeHeadings(doc, translate) : doc}
        showContactIcons={mergedSettings.showContactIcons}
        fallbackName={fallbackName}
      />
    </div>
  );
};

/** Swaps in translated headings, reusing the document when nothing changes. */
function localizeHeadings(doc: ResumeDocument, translate: (key: string) => string): ResumeDocument {
  let changed = false;
  const sections = doc.sections.map((section) => {
    const heading = sectionHeading(section, translate);
    if (heading === section.heading) return section;
    changed = true;
    return { ...section, heading };
  });

  return changed ? { ...doc, sections } : doc;
}

export default Resume;
