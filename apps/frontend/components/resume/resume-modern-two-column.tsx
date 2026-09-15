import React from 'react';
import { visibleSections } from '@/lib/utils/section-helpers';
import type { ResumeTemplateProps } from './template-props';
import { ContactValue } from './contact';
import { SectionBlock } from './section-kinds/section-block';
import baseStyles from './styles/_base.module.css';
import styles from './styles/modern-two-column.module.css';

/**
 * Modern Two-Column Resume Template
 *
 * Two-column layout with modern colorful accents and customizable theme
 * colors. Sections land in the sidebar when `section.column === 'side'`.
 *
 * Best for professionals who want modern aesthetics with a space-efficient
 * layout.
 */
export const ResumeModernTwoColumn: React.FC<ResumeTemplateProps> = ({
  doc,
  showContactIcons = false,
  fallbackName,
}) => {
  const { header } = doc;
  const name = header.name || fallbackName;
  const sections = visibleSections(doc);
  const mainSections = sections.filter((section) => section.column !== 'side');
  const sideSections = sections.filter((section) => section.column === 'side');
  const sidebarHeadingClassName = `${baseStyles['resume-section-title-sm']} text-[var(--resume-accent-primary)]`;

  return (
    <>
      <div className={baseStyles['resume-header']}>
        {name && <h1 className={`${baseStyles['resume-name']} ${styles.nameAccent}`}>{name}</h1>}
        {header.headline && (
          <div className={`${baseStyles['resume-title']} mt-1`}>{header.headline}</div>
        )}
        {header.contacts.length > 0 && (
          <div className={`${baseStyles['resume-meta']} flex flex-wrap gap-x-3 gap-y-1 mt-2`}>
            {header.contacts.map((contact) => (
              <ContactValue key={contact.id} contact={contact} showIcon={showContactIcons} />
            ))}
          </div>
        )}
      </div>

      <div className={styles.grid}>
        <div className={styles.mainColumn}>
          {mainSections.map((section) => (
            <SectionBlock
              key={section.id}
              section={section}
              headingClassName={styles.sectionTitleAccent}
            />
          ))}
        </div>

        <div className={styles.sidebarColumn}>
          {sideSections.map((section) => (
            <SectionBlock
              key={section.id}
              section={section}
              headingClassName={sidebarHeadingClassName}
            />
          ))}
        </div>
      </div>
    </>
  );
};

export default ResumeModernTwoColumn;
