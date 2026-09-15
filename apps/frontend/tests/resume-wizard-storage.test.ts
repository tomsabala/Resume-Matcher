import { afterEach, expect, it } from 'vitest';
import { readResumeWizardDraft } from '@/lib/utils/resume-wizard-storage';

afterEach(() => localStorage.clear());

it('restores a draft, rebuilding section identity and dropping unrenderable sections', () => {
  localStorage.setItem(
    'resume_wizard_draft',
    JSON.stringify({
      schemaVersion: 2,
      state: {
        step: 'question',
        asked_count: 2,
        progress: { current: 8, total: 10 },
        current_question: { text: 'Tell me about your last role.', section: 'section:work' },
        resume_data: {
          header: { name: 'Ada Lovelace', contacts: [{ kind: 'email', value: 'ada@x.io' }] },
          sections: [
            {
              key: 'work',
              heading: 'Experience',
              kind: 'entries',
              column: 'side',
              entries: [
                {
                  title: 'Engineer',
                  period: 2024,
                  bullets: [
                    { text: '   ', style: 'bullet' },
                    { text: 'Plain row', style: 'plain' },
                    { text: 'Bullet row', style: 'nonsense' },
                  ],
                },
                { title: '', bullets: [] },
              ],
            },
            { heading: 'Mystery', kind: 'timeline' },
          ],
        },
      },
    })
  );

  const restored = readResumeWizardDraft();

  expect(restored?.progress.current).toBe(2);
  expect(restored?.current_question.section).toBe('section:work');
  expect(restored?.resume_data.header.name).toBe('Ada Lovelace');
  // Identity is rebuilt: a draft written without an id still dispatches.
  expect(restored?.resume_data.sections).toHaveLength(1);
  const work = restored!.resume_data.sections[0];
  expect(work).toMatchObject({ id: 'work', key: 'work', kind: 'entries', column: 'side' });
  expect(work.visible).toBe(true);
  // A blank bullet is dropped and its neighbours keep their own styles —
  // impossible to desync now that style lives on the bullet.
  expect(work.entries).toHaveLength(1);
  expect(work.entries[0].bullets).toEqual([
    { text: 'Plain row', style: 'plain' },
    { text: 'Bullet row', style: 'bullet' },
  ]);
  expect(work.entries[0].period).toBe('');
});

it('rejects a draft written by the previous schema version', () => {
  localStorage.setItem(
    'resume_wizard_draft',
    JSON.stringify({
      schemaVersion: 1,
      state: { step: 'question', resume_data: { workExperience: [{ title: 'Engineer' }] } },
    })
  );

  expect(readResumeWizardDraft()).toBeNull();
});

it('drops a question whose section discriminator this build cannot act on', () => {
  localStorage.setItem(
    'resume_wizard_draft',
    JSON.stringify({
      schemaVersion: 2,
      state: {
        step: 'question',
        current_question: { text: 'Legacy question', section: 'workExperience' },
        resume_data: { header: {}, sections: [] },
      },
    })
  );

  expect(readResumeWizardDraft()?.current_question.section).toBe('intro');
});
