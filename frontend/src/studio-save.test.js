import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {expect,test} from 'vitest';

function workbench() {
  const saved=new Map(),temporary=new Map();
  const storage=(map,full=false)=>({getItem:k=>map.get(k)||null,removeItem:k=>map.delete(k),setItem:(k,v)=>{if(full&&k.startsWith('video-workspace-save:'))throw Error('quota');map.set(k,v);}});
  const app=runInNewContext(readFileSync(new URL('../public/studio/workflow.js',import.meta.url),'utf8')+';usableCanvas(base)',{
    baseUsableCanvas:v=>v,base:{init(){},persist(){return true;},keydown(){},saveClip(){},assets:[],shots:[],edits:{},narration:'',voice:false,review:'',sequence:[],saved:[],messages:[],candidate:{removed:true},notes:[],narrationNode:{removed:true}},
    localStorage:storage(saved,true),sessionStorage:storage(temporary),crypto:{randomUUID:()=> 'stable-request'},setTimeout,clearTimeout,
  });
  app.workspaceId='project-fixture';app.projectReady=true;app.projectRevision=3;app._ack=JSON.stringify(app.projectSnapshot());
  return {app,saved,temporary};
}

test('a full local cache cannot block saving an imported image to the project',async()=>{
  const {app,saved,temporary}=workbench();app.assets.push({id:'original',file:'data:image/jpeg;base64,actual-pixels'});
  const sent=[];app.projectApi=async(_path,request)=>{sent.push(request);return {revision:4,state:request.state,events:[]};};
  await app.flushProject();
  expect(sent[0].state.assets[0].file).toContain('actual-pixels');expect(app.projectRevision).toBe(4);expect(app.projectStatus).toBe('项目已保存');
  expect(saved.get('video-workspace-03')).not.toContain('actual-pixels');expect(temporary.size).toBe(0);
});

test('a failed save preserves its request and retry does not create a different receipt',async()=>{
  const {app,temporary}=workbench();app.assets.push({id:'original',file:'preserved-pixels'});const sent=[];
  app.projectApi=async(_path,request)=>{sent.push(request);if(sent.length===1)throw Error('offline');return {revision:4,state:request.state,events:[]};};
  await expect(app.flushProject()).rejects.toThrow('offline');expect(temporary.get('video-workspace-save:project-fixture')).toContain('preserved-pixels');
  await app.flushProject();expect(sent[0].request_id).toBe(sent[1].request_id);expect(temporary.has('video-workspace-save:project-fixture')).toBe(false);expect(temporary.has('studio-preview:project-fixture')).toBe(true);
});

test('selecting a node does not leave an already saved project waiting forever',async()=>{
  const {app}=workbench();app.projectStatus='等待保存';
  app.projectApi=()=>{throw Error('view-only selection must not submit a project');};
  await app.flushProject();expect(app.projectStatus).toBe('项目已保存');
});

test('refresh during the debounce restores and saves the latest local draft',async()=>{
  const {app,saved}=workbench();const original=app.projectSnapshot();app.narrationNode={id:'narration',removed:false};app.persist();
  expect(saved.get('video-workspace-draft:project-fixture')).toContain('narration');
  app.narrationNode={removed:true};const sent=[];
  app.projectApi=async(_path,request)=>{if(!request)return {revision:3,state:original,events:[]};sent.push(request);return {revision:4,state:request.state,events:[]};};
  await app.loadSharedProject();expect(app.narrationNode.removed).toBe(false);expect(sent[0].state.narrationNode.removed).toBe(false);
  expect(saved.has('video-workspace-draft:project-fixture')).toBe(false);clearTimeout(app._projectTimer);
});

test('recovering an in-flight receipt never resaves default sample state',async()=>{
  const {app,temporary}=workbench();const state={...app.projectSnapshot(),assets:[{id:'real-product',file:'preserved-pixels'}]};
  temporary.set('video-workspace-save:project-fixture',JSON.stringify({request_id:'old-receipt',revision:3,state}));
  const sent=[];app.projectApi=async(_path,request)=>{sent.push(request);return {revision:4,state:request.state,events:[]};};
  await app.loadSharedProject();expect(sent).toHaveLength(1);expect(app.assets[0].id).toBe('real-product');expect(sent[0].request_id).toBe('old-receipt');
});

test('view-only selection leaves save feedback and draft storage untouched',()=>{
  const {app,saved}=workbench();app.projectStatus='项目已保存';app.selection='picture';app.persist();
  expect(app.projectStatus).toBe('项目已保存');expect(saved.has('video-workspace-draft:project-fixture')).toBe(false);expect(app._projectTimer).toBeUndefined();
});

test('a conflict stops background retry while later edits stay recoverable',async()=>{
  const {app,saved,temporary}=workbench();app.facts='first change';let calls=0;
  app.projectApi=async()=>{calls++;const e=new Error('another window');e.status=409;throw e;};
  await expect(app.flushProject()).rejects.toThrow('another window');const receipt=temporary.get('video-workspace-save:project-fixture');
  app.facts='latest change';app.persist();await expect(app.flushProject()).rejects.toThrow('another window');
  expect(calls).toBe(1);expect(app.projectError).toBe('another window');expect(app.projectStatus).toBe('保存未完成');expect(app._projectTimer).toBeUndefined();
  expect(saved.get('video-workspace-draft:project-fixture')).toContain('latest change');expect(temporary.get('video-workspace-save:project-fixture')).toBe(receipt);
});


test('cached project preview remains read-only and never submits a stale snapshot',async()=>{
  const {app,temporary}=workbench();app.projectReady=false;app.assets=[{id:'cached',file:'/api/media/object'}];app.cacheProjectPreview();app.assets=[];app.readProjectPreview();
  expect(app.projectPreview).toBe(true);expect(app.projectReady).toBe(false);expect(app.assets[0].id).toBe('cached');
  app.projectApi=async()=>{throw Error('offline');};await app.loadSharedProject();
  expect(app.projectLoading).toBe(false);expect(app.projectError).toBe('offline');expect(app.projectReady).toBe(false);
  app.projectApi=()=>{throw Error('preview must never be saved');};await app.flushProject();
  expect(temporary.has('video-workspace-save:project-fixture')).toBe(false);
});

test('cached project preview is replaced by authoritative data before editing',async()=>{
  const {app}=workbench();app.projectReady=false;app.assets=[{id:'old',file:'/api/media/old'}];app.cacheProjectPreview();app.readProjectPreview();
  const latest={...app.projectSnapshot(),assets:[{id:'new',file:'/api/media/new'}]};let reads=0;
  app.projectApi=async()=>{reads++;return {revision:9,state:latest,events:[]};};await Promise.all([app.loadSharedProject(),app.loadSharedProject()]);
  expect(reads).toBe(1);expect(app.assets[0].id).toBe('new');expect(app.projectReady).toBe(true);expect(app.projectPreview).toBe(false);expect(app.projectRevision).toBe(9);
});

test('preview cache does not store large inline images or expired projects',()=>{
  const {app,temporary}=workbench();app.assets=[{id:'inline',file:'data:image/png;base64,abc'}];app.cacheProjectPreview();expect(temporary.has('studio-preview:project-fixture')).toBe(false);
  temporary.set('studio-preview:project-fixture',JSON.stringify({workspace:'project-fixture',at:Date.now()-301000,state:{assets:[{id:'expired'}]}}));app.readProjectPreview();expect(app.assets[0].id).toBe('inline');expect(app.projectPreview).toBe(false);
});
