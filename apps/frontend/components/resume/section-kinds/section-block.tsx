import React from 'react';
import type { Section } from '@/lib/types/document';
import { SECTION_KIND_RENDERERS } from './index';
import { sectionHasContent } from './content';
import baseStyles from '../styles/_base.module.css';

interface SectionBlockProps {
  section: Section;
  /** Template-owned heading typography (the only per-template difference). */
  headingClassName: string;
}

/**
 * Heading + content for one section. Every template renders every section
 * through this, passing its own heading class; empty sections render nothing.
 */
export const SectionBlock: React.FC<SectionBlockProps> = ({ section, headingClassName }) => {
  const Renderer = SECTION_KIND_RENDERERS[section.kind];
  if (!Renderer || !sectionHasContent(section)) return null;

  const heading = section.heading.trim();

  return (
    <div className={baseStyles['resume-section']}>
      {heading && <h3 className={headingClassName}>{heading}</h3>}
      <Renderer section={section} />
    </div>
  );
};
