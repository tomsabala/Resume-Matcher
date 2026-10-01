import { describe, expect, it } from 'vitest';
import { createSection } from '@/lib/utils/section-helpers';
import { emptyDocument } from '@/lib/types/document';

/**
 * A section key is the address space for AI change paths and diff paths. The
 * ASCII-only slug used to collapse every non-Latin heading onto the literal
 * `section`, so a Hebrew resume ended up with `section`, `section_2`, … and AI
 * targeting stopped meaning anything.
 */
describe('createSection key generation', () => {
  it('keeps a readable slug for an ASCII heading', () => {
    const section = createSection(emptyDocument(), 'Military Service', 'entries');
    expect(section.key).toBe('military_service');
  });

  it('suffixes a colliding ASCII slug', () => {
    const doc = emptyDocument();
    doc.sections = [createSection(doc, 'Projects', 'entries')];
    expect(createSection(doc, 'Projects', 'entries').key).toBe('projects_2');
  });

  it('gives a heading with no ASCII alphanumerics its own opaque key', () => {
    const doc = emptyDocument();
    const first = createSection(doc, 'ניסיון מקצועי', 'entries');
    const second = createSection(doc, 'השכלה', 'entries');

    expect(first.key).not.toBe('section');
    expect(first.key).not.toBe(second.key);
    // Must stay inside the character class both path parsers accept.
    expect(first.key).toMatch(/^section_[0-9a-f]{6}$/);
    expect(second.key).toMatch(/^section_[0-9a-f]{6}$/);
  });
});
