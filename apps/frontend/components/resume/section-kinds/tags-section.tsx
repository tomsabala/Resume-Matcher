import React from 'react';
import type { Section } from '@/lib/types/document';
import { nonBlank } from './content';
import styles from '../styles/section-kinds.module.css';

/**
 * `tags` sections render a flat list of short values (skills, languages, ...).
 * Templates decide whether they read as a comma-separated line or as pills —
 * see the custom properties in `section-kinds.module.css`.
 */
export const TagsSection: React.FC<{ section: Section }> = ({ section }) => {
  const tags = nonBlank(section.tags);
  if (tags.length === 0) return null;

  return (
    <div className={styles.tags}>
      {tags.map((tag, index) => (
        <span key={`${tag}-${index}`} className={styles.tag}>
          {tag}
        </span>
      ))}
    </div>
  );
};
