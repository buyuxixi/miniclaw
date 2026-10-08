import { expect, test } from 'vitest';
import { parseBrief, briefDisplay, spokenMain } from './creator-candidates';
const fields = {facts:'乳白壶，材质未验证',selling_points:'外观简洁；审美偏好是建议',audience:'喜欢浅色茶具的人（建议）',style:'自然柔光',constraints:'保留壶型，不编造功能'};
const block = (value: unknown) => '建议如下\n```creator-brief\n' + JSON.stringify(value) + '\n```';
test('only one complete bounded brief may be proposed; extra commands, missing fields and damaged JSON are ignored', () => {
  expect(parseBrief(block(fields))).toEqual(fields);
  expect(parseBrief(block(fields).replace('creator-brief','json'))).toEqual(fields);
  for (const bad of [{...fields, command:'write'}, {...fields, style:null}, {...fields, facts:'x'.repeat(8001)}, {...fields, facts:'x\0'}, {facts:'只给一个'}])
    expect(parseBrief(block(bad))).toBeUndefined();
  expect(parseBrief(block(fields) + '\n' + block(fields))).toBeUndefined();
  expect(parseBrief('```creator-brief\n{broken}\n```')).toBeUndefined();
  expect(briefDisplay(block(fields))).toContain('**目标受众**');
  expect(briefDisplay(block(fields))).not.toContain('creator-brief');
});
test('spoken adoption keeps only the main script, preserving unknown formats for explicit review', () => {
  expect(spokenMain('备注\n```spoken-script\n主稿第一句。\n第二句。\n```\n开头备选')).toBe('主稿第一句。\n第二句。');
  expect(spokenMain('## 口播稿\n主稿。\n\n## 开头备选\n备选。')).toBe('主稿。');
  expect(spokenMain('**口播稿**\n主稿。\n**核对与修改**\n备注。')).toBe('主稿。');
  expect(spokenMain('用户自定义格式完整文本')).toBe('用户自定义格式完整文本');
});
