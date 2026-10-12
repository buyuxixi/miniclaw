import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import { expect, test } from 'vitest';

function workbench(overrides = {}) {
  const saved = new Map(), frames = new Map();
  let frame = 0;
  const context = {
    crypto: { randomUUID: () => 'stable-request' }, URL, URLSearchParams, AbortSignal,
    location: { search: '?workspace=fixture', origin: 'http://localhost' },
    localStorage: { getItem: k => saved.get(k) || null, setItem: (k, v) => saved.set(k, v), removeItem: k => saved.delete(k) },
    sessionStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    setTimeout: () => 1, clearTimeout() {}, setInterval() {},
    matchMedia: () => ({ matches: false }),
    requestAnimationFrame: cb => { frames.set(++frame, cb); return frame; },
    cancelAnimationFrame: id => frames.delete(id),
    ...overrides,
  };
  context.window = context;
  for (const name of ['project-name', 'usability', 'workflow', 'app', 'integration', 'production', 'node-composer', 'interaction'])
    runInNewContext(readFileSync(new URL('../public/studio/' + name + '.js', import.meta.url), 'utf8'), context);
  const app = context.film();
  app.workspaceId = 'fixture';
  app.shots = [{ ...app.shots[0], id: 's1' }, { ...app.shots[0], id: 's2', name: '第二个镜头' }];
  app.notes = [{ id: 'note-1', title: '创意', text: '原方案', x: 0, y: 0, w: 300, h: 240 }];
  app.projectReady = true;
  app.projectRevision = 4;
  app._ack = JSON.stringify(app.projectSnapshot());
  app.$nextTick = cb => cb();
  app.$refs = { world: { clientWidth: 1200, clientHeight: 800, querySelector: () => null, getBoundingClientRect: () => ({ left: 0, top: 0 }) } };
  app.syncDirectorTarget = () => {};
  app.refreshVideo = async () => {};
  app.focusObject = id => { app.focused = id; };
  return { app, context, saved };
}

function changedRecord(app) {
  const state = app.projectSnapshot();
  state.shots[0].prompt = '助手更新后的镜头要求';
  return { revision: 5, state, events: [{ id: 'change-5', object: state.shots[0].id, label: '更新镜头要求' }] };
}

test('authoritative changes update a clean canvas without moving its viewport or selection', async () => {
  const { app } = workbench();
  app.choose('s2');
  const pan = { ...app.pan }, selection = app.selection;
  const record = changedRecord(app);
  app.projectApi = async (path, body) => { expect(body).toBeUndefined(); return record; };
  await app.refreshProjectChanges('助手');
  expect(app.projectRevision).toBe(5);
  expect(app.shots[0].prompt).toBe('助手更新后的镜头要求');
  expect(app._ack).toBe(JSON.stringify(app.projectSnapshot()));
  expect(app.selection).toBe(selection);
  expect(app.pan).toEqual(pan);
  expect(app.projectChangeNotice).toMatchObject({ status: 'applied', revision: 5, changes: [{ object: 's1' }] });
  app.locateProjectChange(app.projectChangeNotice.changes[0]);
  expect(app.selection).toBe('s1');
  expect(app.focused).toBe('s1');
});

test('a dirty draft is preserved and the newer revision blocks background saving', async () => {
  const { app, saved } = workbench();
  const record = changedRecord(app);
  app.shots[0].prompt = '用户尚未保存的镜头要求';
  app.projectApi = async () => record;
  await app.refreshProjectChanges();
  expect(app.shots[0].prompt).toBe('用户尚未保存的镜头要求');
  expect(app.projectRevision).toBe(4);
  expect(app.projectConflict).toBe(true);
  expect(app.projectChangeNotice.status).toBe('conflict');
  expect(saved.get('video-workspace-draft:fixture')).toContain('用户尚未保存的镜头要求');
  await expect(app.flushProject()).rejects.toMatchObject({ status: 409 });
});

test('edits made while a refresh is awaiting the server cannot be overwritten', async () => {
  const { app } = workbench();
  const record = changedRecord(app);
  let release;
  app.projectApi = () => new Promise(resolve => { release = resolve; });
  const refreshing = app.refreshProjectChanges();
  app.notes[0].text = '读取期间输入的草稿';
  release(record);
  await refreshing;
  expect(app.notes[0].text).toBe('读取期间输入的草稿');
  expect(app.projectChangeNotice.status).toBe('conflict');
  expect(app.projectRevision).toBe(4);
});

test('concurrent notifications share one read and a pending receipt is retained', async () => {
  const { app } = workbench();
  const record = changedRecord(app);
  const receipt = { request_id: 'unconfirmed', revision: 4, state: app.projectSnapshot() };
  app._pendingRequest = receipt;
  let reads = 0, release;
  app.projectApi = () => { reads++; return new Promise(resolve => { release = resolve; }); };
  const first = app.refreshProjectChanges(), second = app.refreshProjectChanges();
  release(record);
  await Promise.all([first, second]);
  expect(reads).toBe(1);
  expect(app._pendingRequest).toBe(receipt);
  expect(app.projectChangeNotice.status).toBe('pending');
  expect(app.projectConflict).toBe(false);
});

test('a clean canvas defers updates during a gesture or precision session and applies them afterward', async () => {
  const { app } = workbench();
  const record = changedRecord(app);
  app.projectApi = async () => record;
  for (const field of ['drag', 'fullEditor']) {
    app[field] = true;
    await app.refreshProjectChanges();
    expect(app.projectRevision).toBe(4);
    expect(app.projectChangeNotice.status).toBe('pending');
    app[field] = false;
  }
  await app.refreshProjectChanges();
  expect(app.projectRevision).toBe(5);
  expect(app.projectChangeNotice.status).toBe('applied');
});

test('a save completed during the read keeps an older response from rolling back the canvas', async () => {
  const { app } = workbench();
  const record = changedRecord(app);
  let release;
  app.projectApi = () => new Promise(resolve => { release = resolve; });
  const refreshing = app.refreshProjectChanges();
  app.projectRevision = 6;
  app.facts = '保存到第六版';
  app._ack = JSON.stringify(app.projectSnapshot());
  release(record);
  await refreshing;
  expect(app.projectRevision).toBe(6);
  expect(app.facts).toBe('保存到第六版');
  expect(app.projectChangeNotice).toBeNull();
});

test('a pending notice from this pages own in-flight save clears once that save is acknowledged', async () => {
  const { app } = workbench();
  app.facts = '用户正在保存的修改';
  let finishSave, savedRecord;
  app.projectApi = (path, body) => {
    if (!body) return Promise.resolve(savedRecord);
    savedRecord = { revision: 5, state: body.state, events: [] };
    return new Promise(resolve => { finishSave = () => resolve(savedRecord); });
  };
  const saving = app.flushProject();
  await app.refreshProjectChanges();
  expect(app.projectChangeNotice.status).toBe('pending');
  finishSave();
  await saving;
  expect(app.projectRevision).toBe(5);
  await app.refreshProjectChanges();
  expect(app.projectChangeNotice).toBeNull();
  expect(app.facts).toBe('用户正在保存的修改');
});

test('failed refresh reports retryable feedback while retaining current content', async () => {
  const { app } = workbench();
  const before = JSON.stringify(app.projectSnapshot());
  app.projectApi = async () => { throw Error('网络暂不可用'); };
  await app.refreshProjectChanges();
  expect(JSON.stringify(app.projectSnapshot())).toBe(before);
  expect(app.projectChangeNotice).toMatchObject({ status: 'error', message: '同步画布未完成：网络暂不可用' });
  app.dismissProjectChange();
  expect(app.projectChangeMessage).toBe('');
});

test('assistant and asset notifications validate source and workspace before refreshing', async () => {
  const listeners = {}, channels = [];
  class Channel {
    constructor(name) { this.name = name; channels.push(this); }
    addEventListener(type, callback) { this[type] = callback; }
    close() { this.closed = true; }
  }
  const frame = {};
  const base = { init() {}, $refs: { director: { contentWindow: frame } }, workspaceId: 'fixture' };
  const context = { base, BroadcastChannel: Channel, location: { origin: 'http://localhost' } };
  context.window = { addEventListener: (type, listener) => { listeners[type] = listener; } };
  const app = runInNewContext(readFileSync(new URL('../public/studio/integration.js', import.meta.url), 'utf8') + ';withStudioIntegration(base)', context);
  const refreshed = [];
  app.refreshProjectChanges = source => refreshed.push(source);
  app.init();
  const event = { origin: 'http://localhost', source: frame, data: { type: 'miniclaw.director.changed', workspace: 'fixture' } };
  listeners.message({ ...event, origin: 'https://other.example' });
  listeners.message({ ...event, source: {} });
  listeners.message({ ...event, data: { ...event.data, workspace: 'other' } });
  expect(refreshed).toEqual([]);
  listeners.message(event);
  channels[0].message({ data: { type: 'asset-added', workspace: 'other' } });
  channels[0].message({ data: { type: 'asset-added', workspace: 'fixture' } });
  expect(channels[0].name).toBe('miniclaw-studio');
  expect(refreshed).toEqual(['助手', '项目素材']);
  listeners.pagehide();
  expect(channels[0].closed).toBe(true);
  listeners.pageshow({ persisted: true });
  expect(channels).toHaveLength(2);
  channels[1].message({ data: { type: 'asset-added', workspace: 'fixture' } });
  expect(refreshed).toEqual(['助手', '项目素材', '项目素材']);
});

test('timeline selection locates its source shot and canvas selection locates the adopted clip', () => {
  const { app } = workbench();
  app.sequence = [{ job: 'adopted-1' }, { job: 'adopted-2' }];
  app.videoJobs = [{ id: 'adopted-1', shot: 's1', media: '/first.mp4' }, { id: 'adopted-2', shot: 's2', media: '/second.mp4' }];
  app._ack = JSON.stringify(app.projectSnapshot());
  const sequence = JSON.stringify(app.sequence);
  app.selectAssemblyClip('adopted-2');
  expect(app.assemblyClip).toBe('adopted-2');
  expect(app.active).toBe('s2');
  expect(app.selection).toBe('s2');
  app.locateAssemblyClip();
  expect(app.view).toBe('canvas');
  expect(app.focused).toBe('s2');
  app.openAssemblyForShot('s1');
  expect(app.view).toBe('assemble');
  expect(app.assemblyClip).toBe('adopted-1');
  expect(JSON.stringify(app.sequence)).toBe(sequence);
});

test('an absent timeline result or deleted shot cannot select an unrelated canvas node', () => {
  const { app } = workbench();
  app.sequence = [{ job: 'removed-shot-video' }, { job: 'missing-job' }];
  app.videoJobs = [{ id: 'removed-shot-video', shot: 'deleted-shot' }];
  app.selection = 'source';
  app.selectAssemblyClip('missing-job');
  expect(app.selection).toBe('source');
  app.selectAssemblyClip('removed-shot-video');
  app.locateAssemblyClip();
  expect(app.selection).toBe('source');
  expect(app.toast).toContain('原镜头已移除');
  app.view = 'canvas';
  app.openAssemblyForShot('s2');
  expect(app.view).toBe('canvas');
});

test('source links use the project Chat and only real message ids become anchors', () => {
  const { app } = workbench();
  app.sharedChatId = 'project-chat';
  app.notes.push({ id: 'idea', source: { type: 'chat', sessionId: 'project-chat', messageId: 42 } });
  expect(app.sourceChatHref('idea')).toBe('/c/project-chat?workspace=fixture&target=idea&message=row-42');
  app.notes.at(-1).source.messageId = 'row-42';
  expect(app.sourceChatHref('idea')).toContain('message=row-42');
  app.notes.at(-1).source.messageId = 'attachment-42';
  expect(app.sourceChatHref('idea')).not.toContain('message=');
  const asset = { id: 'image', source: { sessionId: 'project-chat', attachmentId: 'upload-id', objectId: 'media-id', imageJobId: 'job-id', parentId: 'parent-id' } };
  expect(app.sourceChatHref(asset)).toBe('/c/project-chat?workspace=fixture&target=image');
  asset.source.sessionId = 'old-chat';
  asset.source.messageId = 99;
  expect(app.sourceChatHref(asset)).not.toContain('message=');
  expect(app.sourceChatHref(asset)).toContain('/c/project-chat?');
});

test('opening a source waits for durable saving and retains the original destination on failure', async () => {
  const { app, context } = workbench();
  app.sharedChatId = 'project-chat';
  app.selection = 'source';
  const destination = app.selectionSourceHref;
  app.flushProject = async () => { throw Error('连接中断'); };
  await app.openSelectionSource({ preventDefault() {} });
  expect(context.location.href).toBeUndefined();
  expect(app.pendingChatHref).toBe(destination);
  app.selection = 's2';
  app.flushProject = async () => {};
  await app.continueToChat();
  expect(context.location.href).toBe(destination);
});

test('returning from precision restores the same canvas target and leaves content versions intact', () => {
  const { app } = workbench();
  app.editorReturnTarget = 's2';
  app.editAssetId = 'source';
  app.fullEditor = true;
  app.assets[0].versions = [{ file: '/before.png' }, { file: '/after.png' }];
  app.assets[0].documentVersion = 'formal-version';
  app.closeFullEditor();
  expect(app.fullEditor).toBe(false);
  expect(app.selection).toBe('s2');
  expect(app.focused).toBe('s2');
  expect(app.assets[0].documentVersion).toBe('formal-version');
  expect(app.assets[0].versions).toHaveLength(2);
});

test('explicit precision adoption returns to its original shot with the adopted version and provenance', async () => {
  const { app } = workbench();
  const state = app.projectSnapshot();
  const original = state.assets[0];
  const derived = { ...original, id: 'repaired-input', file: '/repaired.png', editProject: 'precision-project', documentVersion: 'new-document-version', versions: [{ file: original.file }], source: { sessionId: 'project-chat', parentId: original.id, imageJobId: 'image-result' } };
  state.assets.push(derived);
  state.shots[0].first = derived.id;
  state.shots[0].inputReview = true;
  const messages = [];
  app.$refs.director = { contentWindow: { postMessage: m => messages.push(m) } };
  Object.assign(app, { editorCandidate: { revision: 8, output_id: 'exported-image', output: '/repaired.png' }, editorProject: 'precision-project', editAssetId: original.id, editSource: { file: original.file }, editorReturnTarget: 's1', adoptShot: 's1', compareBasis: 4, fullEditor: true });
  app.flushProject = async () => {};
  app.projectApi = async (path, request) => {
    expect(path).toBe('/commands');
    expect(request.args).toMatchObject({ object: original.id, shot: 's1', asset: 'exported-image' });
    return { revision: 5, state, events: [] };
  };
  await app.adoptFullEditor();
  expect(app.selection).toBe('s1');
  expect(app.focused).toBe('s1');
  expect(app.shots[0].first).toBe('repaired-input');
  expect(app.assets.find(a => a.id === derived.id).documentVersion).toBe('new-document-version');
  expect(messages).toContainEqual({ type: 'miniclaw.director.image', workspace: 'fixture', target: 's1', asset: 'repaired-input' });
});

test('local changes made during precision adoption survive its returned server state', async () => {
  const { app, saved } = workbench();
  const state = app.projectSnapshot();
  const asset = { ...state.assets[0] };
  state.assets[0].file = '/repaired.png';
  Object.assign(app, { editorCandidate: { revision: 8, output_id: 'exported-image', output: '/repaired.png' }, editorProject: 'precision-project', editAssetId: asset.id, editSource: { file: asset.file }, compareBasis: 4, fullEditor: true });
  app.flushProject = async () => {};
  let release, submitted;
  const waiting = new Promise(resolve => { submitted = resolve; });
  app.projectApi = () => { submitted(); return new Promise(resolve => { release = resolve; }); };
  const adopting = app.adoptFullEditor();
  await waiting;
  app.notes[0].text = '采用期间新写的想法';
  release({ revision: 5, state, events: [{ id: 'adopted', object: asset.id, label: '采用精修结果' }] });
  await adopting;
  expect(app.notes[0].text).toBe('采用期间新写的想法');
  expect(app.assets[0].file).not.toBe('/repaired.png');
  expect(app.projectRevision).toBe(4);
  expect(app.projectConflict).toBe(true);
  expect(app.editorFailure).toContain('精修结果已保存到项目');
  expect(saved.get('video-workspace-draft:fixture')).toContain('采用期间新写的想法');
  expect(saved.has('studio-adopt:fixture')).toBe(true);
});
