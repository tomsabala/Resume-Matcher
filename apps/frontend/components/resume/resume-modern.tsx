import React from 'react';
import { visibleSections } from '@/lib/utils/section-helpers';
import type { ResumeTemplateProps } from './template-props';
import { ContactValue } from './contact';
import { SectionBlock } from './section-kinds/section-block';
import baseStyles from './styles/_base.module.css';
import styles from './styles/modern.module.css';

/**
 * Modern Resume Template
 *
 * Single-column layout with user-selectable accent colors: colored section
 * headers with underline and a decorative name underline.
 * ATS-compatible: all visual elements are real DOM text nodes.
 */
export const ResumeModern: React.FC<ResumeTemplateProps> = ({
  doc,
  showContactIcons = false,
  fallbackName,
}) => {
  const { header } = doc;
  const name = header.name || fallbackName;

  return (
    <div className={styles.container}>
      <header className={`text-center ${baseStyles['resume-header']}`}>
        {name && (
          <h1 className={`${baseStyles['resume-name']} tracking-tight uppercase mb-1`}>{name}</h1>
        )}

        <div className={styles['name-underline']} aria-hidden="true" />

        {header.headline && (
          <h2
            className={`${baseStyles['resume-title']} ${baseStyles['resume-meta']} tracking-wide uppercase mt-3 mb-3`}
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

      {visibleSections(doc).map((section) => (
        <SectionBlock
          key={section.id}
          section={section}
          headingClassName={styles['section-title-accent']}
        />
      ))}
    </div>
  );
};

export default ResumeModern;
