import React from 'react';
import { visibleSections } from '@/lib/utils/section-helpers';
import type { ResumeTemplateProps } from './template-props';
import { ContactValue } from './contact';
import { SectionBlock } from './section-kinds/section-block';
import baseStyles from './styles/_base.module.css';
import styles from './styles/clean.module.css';

/**
 * Clean Resume Template
 *
 * Minimal modern sans layout: centered light-weight name, a single
 * pipe-separated contact line and large understated gray UPPERCASE section
 * headers with a thin rule.
 *
 * Single-typeface design: all text inherits `--body-font` (sans by default), so
 * the Body Font control drives the whole template. ATS-safe (all text is real
 * DOM nodes).
 */
export const ResumeClean: React.FC<ResumeTemplateProps> = ({
  doc,
  showContactIcons = false,
  fallbackName,
}) => {
  const { header } = doc;
  const name = header.name || fallbackName;

  return (
    <div className={styles.container}>
      <header className={`text-center ${baseStyles['resume-header']}`}>
        {name && <h1 className={`${styles.name} mb-1`}>{name}</h1>}
        {header.headline && <div className={`${styles.tagline} mb-1`}>{header.headline}</div>}
        {header.contacts.length > 0 && (
          <div
            className={`flex flex-wrap justify-center items-center gap-x-2 gap-y-1 ${styles.contactRow}`}
          >
            {header.contacts.map((contact, index) => (
              <React.Fragment key={contact.id}>
                {index > 0 && <span className={styles.sep}>|</span>}
                <ContactValue contact={contact} showIcon={showContactIcons} />
              </React.Fragment>
            ))}
          </div>
        )}
      </header>

      {visibleSections(doc).map((section) => (
        <SectionBlock key={section.id} section={section} headingClassName={styles.sectionTitle} />
      ))}
    </div>
  );
};

export default ResumeClean;
