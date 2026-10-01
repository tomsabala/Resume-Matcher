import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest';
import {
  answerPrepCard,
  bulkCreatePrepCards,
  bulkDeletePrepCards,
  createPrepCard,
  critiquePrepCard,
  deletePrepCard,
  generatePrepCards,
  listPrepCards,
  updatePrepCard,
} from '@/lib/api/prep-cards';

/**
 * Prep-card API client contracts: each wrapper must hit the right method/URL
 * and send the right payload. A drifting path or body is a silent 404/422.
 */

describe('prep-cards API client', () => {
  let fetchMock: Mock;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const lastCall = () => {
    const [url, options] = fetchMock.mock.calls.at(-1)!;
    return { url: String(url), options: options as RequestInit };
  };

  // A Response body can only be read once, so every call needs a fresh one.
  const resolveWith = (body: unknown) =>
    fetchMock.mockImplementation(async () => new Response(JSON.stringify(body), { status: 200 }));

  it('listPrepCards GETs /prep-cards and filters by category when given one', async () => {
    resolveWith({ cards: [] });
    await listPrepCards();
    expect(lastCall().url).toContain('/prep-cards');
    expect(lastCall().url).not.toContain('category=');

    await listPrepCards('personal');
    expect(lastCall().url).toContain('/prep-cards?category=personal');
  });

  it('createPrepCard POSTs /prep-cards with the card body', async () => {
    resolveWith({ card_id: 'c1' });
    await createPrepCard({ category: 'technical', question: 'What is WAL?', answer: null });
    const { url, options } = lastCall();
    expect(url).toContain('/prep-cards');
    expect(options.method).toBe('POST');
    expect(JSON.parse(String(options.body))).toEqual({
      category: 'technical',
      question: 'What is WAL?',
      answer: null,
    });
  });

  it('bulkCreatePrepCards POSTs /prep-cards/bulk-create wrapped in `cards`', async () => {
    resolveWith({ cards: [] });
    await bulkCreatePrepCards([{ category: 'personal', question: 'Why us?' }]);
    const { url, options } = lastCall();
    expect(url).toContain('/prep-cards/bulk-create');
    expect(options.method).toBe('POST');
    expect(JSON.parse(String(options.body))).toEqual({
      cards: [{ category: 'personal', question: 'Why us?' }],
    });
  });

  it('updatePrepCard PATCHes /prep-cards/{id} with the partial', async () => {
    resolveWith({ card_id: 'c1' });
    await updatePrepCard('c1', { confidence: 'good' });
    const { url, options } = lastCall();
    expect(url).toContain('/prep-cards/c1');
    expect(options.method).toBe('PATCH');
    expect(JSON.parse(String(options.body))).toEqual({ confidence: 'good' });
  });

  it('deletePrepCard DELETEs /prep-cards/{id}', async () => {
    resolveWith({ message: 'ok', affected: 1 });
    await deletePrepCard('c1');
    const { url, options } = lastCall();
    expect(url).toContain('/prep-cards/c1');
    expect(options.method).toBe('DELETE');
  });

  it('bulkDeletePrepCards POSTs /prep-cards/bulk-delete with card_ids', async () => {
    resolveWith({ message: 'ok', affected: 2 });
    await bulkDeletePrepCards(['a', 'b']);
    const { url, options } = lastCall();
    expect(url).toContain('/prep-cards/bulk-delete');
    expect(options.method).toBe('POST');
    expect(JSON.parse(String(options.body))).toEqual({ card_ids: ['a', 'b'] });
  });

  it('generatePrepCards POSTs /prep-cards/generate with the request', async () => {
    resolveWith({ proposals: [] });
    await generatePrepCards({ category: 'technical', count: 3 });
    const { url, options } = lastCall();
    expect(url).toContain('/prep-cards/generate');
    expect(options.method).toBe('POST');
    expect(JSON.parse(String(options.body))).toEqual({ category: 'technical', count: 3 });
  });

  it('answerPrepCard POSTs /prep-cards/{id}/answer', async () => {
    resolveWith({ card_id: 'c1' });
    await answerPrepCard('c1');
    const { url, options } = lastCall();
    expect(url).toContain('/prep-cards/c1/answer');
    expect(options.method).toBe('POST');
  });

  it('critiquePrepCard POSTs /prep-cards/{id}/critique with my_answer', async () => {
    resolveWith({ card_id: 'c1' });
    await critiquePrepCard('c1', 'Because I like it.');
    const { url, options } = lastCall();
    expect(url).toContain('/prep-cards/c1/critique');
    expect(options.method).toBe('POST');
    expect(JSON.parse(String(options.body))).toEqual({ my_answer: 'Because I like it.' });
  });

  it('surfaces the FastAPI detail string when a request fails', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Card not found' }), { status: 404 })
    );
    await expect(updatePrepCard('nope', { confidence: 'easy' })).rejects.toThrow('Card not found');
  });
});
