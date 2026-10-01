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
          {group.label && (
            <span className={styles.groupLabel} dir="auto">
              {group.label}
            </span>
          )}
          {/* The comma-separated run reads as one sentence, so the *list* takes
              its direction from its own first strong character (`dir="auto"` on
              the container) while each value is isolated with `<bdi>`. Putting
              `dir="auto"` on the values instead reversed a Latin list inside a
              Hebrew resume and detached its separators. */}
          <span className={styles.groupValues} dir="auto">
            {group.values.map((value, valueIndex) => (
              <React.Fragment key={`${value}-${valueIndex}`}>
                {valueIndex > 0 ? ', ' : ''}
                <bdi>{value}</bdi>
              </React.Fragment>
            ))}
          </span>
        </div>
      ))}
    </div>
  );
};
