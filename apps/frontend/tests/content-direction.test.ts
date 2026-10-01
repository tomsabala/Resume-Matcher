import { describe, expect, it } from 'vitest';
import {
  containsScript,
  detectContentLanguage,
  directionForContent,
} from '@/lib/utils/content-direction';

/**
 * The document decides the render direction, not the workspace: a Hebrew resume
 * in an English workspace painted left-to-right is the bug this guards.
 *
 * The LaTeX guard is a different predicate on purpose — *any* Hebrew letter
 * breaks the Latin-only preamble, even in a document that is plainly English.
 */
const hebrewDoc = {
  sections: [{ text: 'מהנדס תוכנה עם שש שנות ניסיון בפיתוח מערכות צד שרת' }],
};
const englishDoc = {
  sections: [{ text: 'Software engineer with six years building server-side systems.' }],
};
const docWithOneHebrewBullet = {
  sections: [
    { text: 'Software engineer with six years building server-side systems.' },
    { bullets: ['Led the React migration', 'שלום'] },
  ],
};

describe('directionForContent', () => {
  it('flips a Hebrew document in an English workspace', () => {
    expect(directionForContent(hebrewDoc, 'en')).toBe('rtl');
  });

  it('keeps an English document left-to-right in a Hebrew workspace', () => {
    expect(directionForContent(englishDoc, 'he')).toBe('ltr');
  });

  it('falls back to the workspace while the document is too short to judge', () => {
    expect(directionForContent({ header: { name: 'Tom' } }, 'he')).toBe('rtl');
    expect(directionForContent({}, 'en')).toBe('ltr');
  });
});

describe('the LaTeX predicate', () => {
  it('fires on one Hebrew word in an otherwise English document', () => {
    expect(containsScript(docWithOneHebrewBullet, 'he')).toBe(true);
    expect(detectContentLanguage(docWithOneHebrewBullet)).toBe('en');
  });

  it('stays quiet on a Latin-only document', () => {
    expect(containsScript(englishDoc, 'he')).toBe(false);
  });
});

describe('detectContentLanguage', () => {
  it('does not let English schema keys outvote Hebrew values', () => {
    expect(detectContentLanguage({ workExperience: hebrewDoc, schemaVersion: 2 })).toBe('he');
  });

  it('keeps a Latin-dense Hebrew bullet Hebrew', () => {
    const bullet = 'הובלתי מעבר ל-React ושיפרתי את זמן הטעינה ב-30%';
    expect(detectContentLanguage([bullet, bullet])).toBe('he');
  });
});
