import React from 'react';
import type { Section } from '@/lib/types/document';
import { nonBlank } from './content';
import styles from '../styles/section-kinds.module.css';

/**
 * `groups` sections render labelled value lists — one row per group, e.g.
 * "Technical Skills: Python, TypeScript".
 */
export const GroupsSection: React.FC<{ section: Section }> = ({ section }) => {
  const groups = section.groups
    .map((group) => ({ label: group.label.trim(), values: nonBlank(group.values) }))
    .filter((group) => group.values.length > 0);

  if (groups.length === 0) return null;

  return (
    <div className={styles.groups}>
      {groups.map((group, index) => (
        <div key={`${group.label}-${index}`} className={styles.group}>
          {group.label && <span className={styles.groupLabel}>{group.label}</span>}
          <span className={styles.groupValues}>{group.values.join(', ')}</span>
        </div>
      ))}
    </div>
  );
};
