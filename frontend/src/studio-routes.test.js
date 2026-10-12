import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {expect,test} from 'vitest';
const helpers=location=>{
  const scope={location,URLSearchParams};
  runInNewContext(readFileSync(new URL('../public/studio/project-name.js',import.meta.url),'utf8'),scope);
  return scope;
};
test('canonical routes encode identifiers and preserve the project and node across Chat navigation',()=>{
  const h=helpers({pathname:'/p/project-one',search:'?focus=shot-one'});
  expect(h.studioWorkspaceId()).toBe('project-one');
  expect(h.studioCanvasHref('project-one','shot one')).toBe('/p/project-one?focus=shot%20one');
  expect(h.studioChatHref('session/one','project-one','shot one')).toBe('/c/session%2Fone?workspace=project-one&target=shot+one');
  expect(h.studioChatHref()).toBe('/');
  expect(helpers({pathname:'/studio/index.html',search:'?workspace=legacy'}).studioWorkspaceId()).toBe('legacy');
});
test('display summaries remove formatting without rewriting the stored source',()=>{
  const h=helpers({});const asset={name:'7cc469c92948ef926be28a593509ac59.jpg'};
  expect(h.studioAssetName(asset,1)).toBe('图片 2');expect(asset.name).toContain('7cc469');
  expect(h.studioAssetName({name:'产品正面.png'})).toBe('产品正面.png');
  const source='## 方向\n**保留包装**，查看[参考](https://example.com)\n```json\n{}\n```';
  expect(h.studioNotePreview(source)).toBe('方向\n保留包装，查看参考');expect(source).toContain('```json');
});
