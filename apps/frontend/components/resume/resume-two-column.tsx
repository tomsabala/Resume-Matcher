import React from 'react';
import { visibleSections } from '@/lib/utils/section-helpers';
import type { ResumeTemplateProps } from './template-props';
import { ContactValue } from './contact';
import { SectionBlock } from './section-kinds/section-block';
import baseStyles from './styles/_base.module.css';
import styles from './styles/swiss-two-column.module.css';

/**
 * Swiss Two-Column Resume Template
 *
 * Two-column layout with a content-focused main column (65%) and a supporting
 * sidebar (35%). Placement is data: a section goes to the sidebar when
 * `section.column === 'side'`, so any section — built-in or user-authored —
 * can live in either column.
 *
 * Best for technical roles with many projects, optimized for one-page resumes.
 */
export const ResumeTwoColumn: React.FC<ResumeTemplateProps> = ({
  doc,
  showContactIcons = false,
  fallbackName,
}) => {
  const { header } = doc;
  const name = header.name || fallbackName;
  const sections = visibleSections(doc);
  const mainSections = sections.filter((section) => section.column !== 'side');
  const sideSections = sections.filter((section) => section.column === 'side');

  return (
    <>
      <header
        className={`text-center ${baseStyles['resume-header']} border-b`}
        style={{ borderColor: 'var(--resume-border-primary)' }}
      >
        {name && (
          <h1 className={`${baseStyles['resume-name']} tracking-tight uppercase mb-1`}>{name}</h1>
        )}

        {header.headline && (
          <h2
            className={`${baseStyles['resume-title']} ${baseStyles['resume-meta']} tracking-wide uppercase mb-3`}
          >
            {header.headline}
          </h2>
        )}

        {header.contacts.length > 0 && (
          <div
            className={`flex flex-wrap justify-center gap-x-1 gap-y-1 ${baseStyles['resume-meta']}`}
          >
            {header.contacts.map((contact, index) => (
              <React.Fragment key={contact.id}>
                {index > 0 && <span className={baseStyles['text-muted']}>,</span>}
                <ContactValue contact={contact} showIcon={showContactIcons} />
              </React.Fragment>
            ))}
          </div>
        )}
      </header>

      <div className={styles.grid}>
        <div className={styles.mainColumn}>
          {mainSections.map((section) => (
            <SectionBlock
              key={section.id}
              section={section}
              headingClassName={baseStyles['resume-section-title']}
            />
          ))}
        </div>

        <div className={styles.sidebarColumn}>
          {sideSections.map((section) => (
            <SectionBlock
              key={section.id}
              section={section}
              headingClassName={baseStyles['resume-section-title-sm']}
            />
          ))}
        </div>
      </div>
    </>
  );
};

export default ResumeTwoColumn;
