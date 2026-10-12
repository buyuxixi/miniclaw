import { expect, test } from 'vitest';
import { historyItems } from './transcript';
import { imageOptimizationMessage, shotOptimizationMessage } from './fixtures/legacy-director-prompts';

test('legacy app optimization scaffolding displays only the question without losing newlines', () => {
  const goal = '那怎么改？\n改提示词还是怎么改？ "quoted" {数据}';
  for (const text of [shotOptimizationMessage({name:'真人清新',prompt:'隐藏旧提示词'},goal),imageOptimizationMessage({name:'图',prompt:'隐藏旧提示词'},goal,'image-edit')]) {
    const item = historyItems([{role:'user',row_id:1,text:'/product-prompt-optimize\n'+text}])[0];
    expect(item.text).toBe('/product-prompt-optimize\n'+goal);
  }
});

test('ordinary questions, pasted JSON and assistant examples stay verbatim', () => {
  for (const text of ['请讲解 requested_change 的用途', '{"requested_change":"用户JSON"}', '参考：'+shotOptimizationMessage({name:'镜头',prompt:'保持'},'讨论一下')]) {
    expect(historyItems([{role:'user',text}])[0].text).toBe(text);
  }
  const text=shotOptimizationMessage({name:'镜头',prompt:'保持'},'讨论一下');
  expect(historyItems([{role:'assistant',text}])[0].text).toBe(text);
  expect(historyItems([{role:'user',text:text.replace('"requested_change":"讨论一下"','"requested_change":null')}])[0].text).not.toBe('null');
});
