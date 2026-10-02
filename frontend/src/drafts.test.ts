import { afterEach, expect, test, vi } from 'vitest';
import { loadDraft, saveDraft } from './drafts';
import { skillReadiness } from './skill-readiness';
afterEach(() => vi.unstubAllGlobals());
test('drafts remain separate across sessions and reload with selected attachment ids', () => {
  const store = new Map<string, string>();
  vi.stubGlobal('localStorage', { getItem: (k: string) => store.get(k), setItem: (k: string, v: string) => store.set(k, v) });
  const draft = { text: 'first draft', skill: 'lesson', attachments: [{ id: 'file-1', name: 'a.md', kind: 'text' as const, mime: 'text/plain', bytes: 30 }] };
  saveDraft('one', draft); saveDraft('two', { text: 'another', attachments: [] });
  expect(loadDraft('one')).toEqual(draft); expect(loadDraft('two').text).toBe('another');
  saveDraft('one', { text: '', attachments: [] }); expect(loadDraft('two').text).toBe('another');
});
test('a malformed or unavailable browser store does not break chat', () => {
  vi.stubGlobal('localStorage', { getItem: () => '{invalid', setItem: () => { throw new Error('quota'); } });
  expect(loadDraft('one')).toEqual({ text: '', attachments: [] }); expect(saveDraft('one', { text: 'keep', attachments: [] })).toBe(false);
});
test('a bound tool is still missing until this session actually loaded it', () => {
  const skill = { name: 'lesson', enabled: true, binding: { version: 1, required_tools: ['miniclaw_save_artifact'], content_hash: 'sha', current: true } };
  expect(skillReadiness(skill, ['miniclaw_read_file']).state).toBe('missing');
  expect(skillReadiness(skill, ['miniclaw_save_artifact']).state).toBe('ready');
  expect(skillReadiness({ ...skill, binding: { ...skill.binding, current: false } }, ['miniclaw_save_artifact']).state).toBe('unverified');
});
