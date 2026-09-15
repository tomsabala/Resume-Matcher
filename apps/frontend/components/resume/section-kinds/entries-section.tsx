import React from 'react';
import type { Bullet, Entry, Section } from '@/lib/types/document';
import { EntryLinkPill } from '../contact';
import { SafeHtml } from '../safe-html';
import baseStyles from '../styles/_base.module.css';
import styles from '../styles/section-kinds.module.css';

/**
 * Bullet rows. `style` is a property of the bullet, so a `plain` row renders as
 * a paragraph with no marker and no marker indent.
 */
const Bullets: React.FC<{ bullets: Bullet[] }> = ({ bullets }) => {
  const rows = bullets.filter((bullet) => bullet.text.trim() !== '');
  if (rows.length === 0) return null;

  return (
    <ul className={styles.bullets}>
      {rows.map((bullet, index) => (
        <li
          key={index}
          data-bullet-style={bullet.style}
          className={bullet.style === 'plain' ? styles.plainRow : styles.bulletRow}
        >
          {bullet.style !== 'plain' && (
            <span className={styles.marker} aria-hidden="true">
              &bull;&nbsp;
            </span>
          )}
          <span>
            <SafeHtml html={bullet.text} />
          </span>
        </li>
      ))}
    </ul>
  );
};

const EntryRow: React.FC<{ entry: Entry }> = ({ entry }) => {
  const links = entry.links.filter((link) => link.url.trim() !== '');
  const summary = entry.summary.trim();

  return (
    <div className={baseStyles['resume-item']}>
      <div className={`flex justify-between items-baseline ${baseStyles['resume-row-tight']}`}>
        <span className="flex items-baseline gap-2 min-w-0">
          {entry.title && <h4 className={baseStyles['resume-item-title']}>{entry.title}</h4>}
          {links.length > 0 && (
            <span className={styles.entryLinks}>
              {links.map((link, index) => (
                <EntryLinkPill key={`${link.url}-${index}`} link={link} />
              ))}
            </span>
          )}
        </span>
        {entry.period && (
          <span className={`${baseStyles['resume-date']} ml-4`}>{entry.period}</span>
        )}
      </div>

      {(entry.subtitle || entry.meta) && (
        <div
          className={`flex justify-between items-baseline gap-3 ${baseStyles['resume-row-tight']} ${baseStyles['resume-item-subtitle']}`}
        >
          {entry.subtitle && <span className="min-w-0">{entry.subtitle}</span>}
          {entry.meta && <span className="shrink-0">{entry.meta}</span>}
        </div>
      )}

      {summary && <p className={styles.entrySummary}>{summary}</p>}

      <Bullets bullets={entry.bullets} />
    </div>
  );
};

/**
 * `entries` sections render repeated rows — jobs, degrees, projects, military
 * postings. Field names are generic because the shape is generic.
 */
export const EntriesSection: React.FC<{ section: Section }> = ({ section }) => {
  if (section.entries.length === 0) return null;

  return (
    <div className={baseStyles['resume-items']}>
      {section.entries.map((entry) => (
        <EntryRow key={entry.id} entry={entry} />
      ))}
    </div>
  );
};
