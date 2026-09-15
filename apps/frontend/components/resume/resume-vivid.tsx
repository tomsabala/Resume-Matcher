import React from 'react';
import { visibleSections } from '@/lib/utils/section-helpers';
import type { ResumeTemplateProps } from './template-props';
import { ContactValue } from './contact';
import { SectionBlock } from './section-kinds/section-block';
import baseStyles from './styles/_base.module.css';
import styles from './styles/vivid.module.css';

/**
 * Vivid Resume Template
 *
 * Colorful two-column layout in the "Awesome-CV" lineage: a two-tone accent
 * name, a monospace headline + contact row with circular icon chips, accent
 * small-caps section headers and accent bullet markers. Reads the accent-color
 * control (default blue). ATS-safe (all text is real DOM nodes).
 *
 * Sections land in the sidebar when `section.column === 'side'`.
 */
export const ResumeVivid: React.FC<ResumeTemplateProps> = ({
  doc,
  showContactIcons = false,
  fallbackName,
}) => {
  const { header } = doc;
  const sections = visibleSections(doc);
  const mainSections = sections.filter((section) => section.column !== 'side');
  const sideSections = sections.filter((section) => section.column === 'side');

  // Two-tone name: bold accent first token, lighter accent for the rest.
  const fullName = header.name || fallbackName || '';
  const firstSpace = fullName.indexOf(' ');
  const nameFirst = firstSpace === -1 ? fullName : fullName.slice(0, firstSpace);
  const nameRest = firstSpace === -1 ? '' : fullName.slice(firstSpace + 1);

  return (
    <>
      <div className={baseStyles['resume-header']}>
        {fullName && (
          <h1 className={baseStyles['resume-name']}>
            <span className={styles.nameFirst}>{nameFirst}</span>
            {nameRest && <span className={styles.nameRest}> {nameRest}</span>}
          </h1>
        )}
        {header.headline && <div className={styles.titleLine}>{header.headline}</div>}
        {header.contacts.length > 0 && (
          <div className={`flex flex-wrap gap-x-4 gap-y-1 mt-2 ${styles.contactRow}`}>
            {header.contacts.map((contact) => (
              <ContactValue
                key={contact.id}
                contact={contact}
                showIcon={showContactIcons}
                iconSize={11}
                className={styles.contactChip}
                iconClassName={styles.iconCircle}
              />
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
              headingClassName={styles.sectionTitle}
            />
          ))}
        </div>

        <div className={styles.sidebarColumn}>
          {sideSections.map((section) => (
            <SectionBlock
              key={section.id}
              section={section}
              headingClassName={styles.sectionTitleSm}
            />
          ))}
        </div>
      </div>
    </>
  );
};

export default ResumeVivid;
