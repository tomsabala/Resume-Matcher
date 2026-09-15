import React from 'react';
import { visibleSections } from '@/lib/utils/section-helpers';
import type { ResumeTemplateProps } from './template-props';
import { ContactValue } from './contact';
import { SectionBlock } from './section-kinds/section-block';
import baseStyles from './styles/_base.module.css';
import styles from './styles/latex.module.css';

/**
 * LaTeX Resume Template
 *
 * Classic serif academic layout reminiscent of the popular LaTeX résumé
 * templates: centered small-caps name, a middot-separated contact row and
 * Title-Case section headers with a full-width rule. Location keeps its own
 * centered line, as in the original class files.
 *
 * Single-typeface design: all text inherits `--header-font` (serif by default),
 * so the Header Font control drives the whole template.
 */
export const ResumeLatex: React.FC<ResumeTemplateProps> = ({
  doc,
  showContactIcons = false,
  fallbackName,
}) => {
  const { header } = doc;
  const name = header.name || fallbackName;
  const locations = header.contacts.filter((contact) => contact.kind === 'location');
  const inlineContacts = header.contacts.filter((contact) => contact.kind !== 'location');

  return (
    <div className={styles.container}>
      <header className={`text-center ${baseStyles['resume-header']}`}>
        {name && <h1 className={`${styles.name} mb-1`}>{name}</h1>}
        {header.headline && <div className={`${styles.tagline} mb-1`}>{header.headline}</div>}
        {locations.map((contact) => (
          <div key={contact.id} className={`${styles.locationLine} mb-1`}>
            <ContactValue contact={contact} showIcon={showContactIcons} />
          </div>
        ))}
        {inlineContacts.length > 0 && (
          <div
            className={`flex flex-wrap justify-center items-center gap-x-2 gap-y-1 ${styles.contactRow}`}
          >
            {inlineContacts.map((contact, index) => (
              <React.Fragment key={contact.id}>
                {index > 0 && <span className={styles.contactSep}>·</span>}
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

export default ResumeLatex;
