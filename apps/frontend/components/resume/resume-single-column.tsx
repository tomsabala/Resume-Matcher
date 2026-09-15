import React from 'react';
import { visibleSections } from '@/lib/utils/section-helpers';
import type { ResumeTemplateProps } from './template-props';
import { ContactValue } from './contact';
import { SectionBlock } from './section-kinds/section-block';
import baseStyles from './styles/_base.module.css';
import styles from './styles/swiss-single.module.css';

/**
 * Swiss Single-Column Resume Template
 *
 * Traditional full-width layout with sections stacked vertically.
 * Best for detailed experience descriptions and maximum content density.
 *
 * Header comes from `doc.header`; everything below it is `doc.sections` in
 * document order, rendered through the section-kind registry.
 */
export const ResumeSingleColumn: React.FC<ResumeTemplateProps> = ({
  doc,
  showContactIcons = false,
  fallbackName,
}) => {
  const { header } = doc;
  const name = header.name || fallbackName;

  return (
    <div className={styles.container}>
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

      {visibleSections(doc).map((section) => (
        <SectionBlock
          key={section.id}
          section={section}
          headingClassName={baseStyles['resume-section-title']}
        />
      ))}
    </div>
  );
};

export default ResumeSingleColumn;
