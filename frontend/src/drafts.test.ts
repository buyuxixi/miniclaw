import { afterEach, expect, test, vi } from 'vitest';
import { loadDraft, saveDraft } from './drafts';
import { skillDetails, skillReadiness } from './skill-readiness';
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
test('ten mixed document references survive a draft reload without being truncated to the former four',()=>{
  const store=new Map<string,string>();vi.stubGlobal('localStorage',{getItem:(k:string)=>store.get(k),setItem:(k:string,v:string)=>store.set(k,v)});
  const draft={text:'分析这些资料',attachments:Array.from({length:10},(_,i)=>({id:`doc-${i}`,name:`资料${i}.pdf`,kind:'document' as const,mime:'application/pdf',bytes:500,parse_status:'ready' as const}))};
  saveDraft('owner',draft);expect(loadDraft('owner')).toEqual(draft);
});
test('a bound tool is still missing until this session actually loaded it', () => {
  const skill = { name: 'lesson', enabled: true, binding: { version: 1, required_tools: ['miniclaw_save_artifact'], content_hash: 'sha', current: true } };
  expect(skillReadiness(skill, ['miniclaw_read_file']).state).toBe('missing');
  expect(skillReadiness(skill, ['miniclaw_save_artifact']).state).toBe('ready');
  expect(skillReadiness({ ...skill, binding: { ...skill.binding, current: false } }, ['miniclaw_save_artifact']).state).toBe('unverified');
});

test('custom skill identifiers that match Object properties still display their own description', () => {
  expect(skillDetails({ name: 'constructor', description: 'custom flow' })).toEqual({ title: 'constructor', description: 'custom flow' });
});

test('a declared flow with missing package resources is unavailable even when its tools loaded', () => {
  const skill = { name: 'mono-color', enabled: true, binding: { version: 1, required_tools: ['skill_view'], content_hash: 'sha', current: false, resource_error: '配套资料缺失：colors.json' } };
  expect(skillReadiness(skill, ['skill_view'])).toEqual({ state: 'missing', label: '配套资料不可用', reason: '配套资料缺失：colors.json' });
});
