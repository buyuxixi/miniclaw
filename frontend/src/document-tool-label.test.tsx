// @vitest-environment jsdom
import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,test,vi} from 'vitest';
import {Message} from './Message';
import {TraceView} from './TraceView';
import {historyItems} from './transcript';
import {withTraceHistory} from './trace-history';
import type {HistoryRow} from './types';

let root:Root,host:HTMLDivElement;
const name='miniclaw_document_query';
const history:HistoryRow[]=[
  {role:'tool',tool_call_id:'single',name,args:'{"action":"search","query":"附件"}',content:'{"success":true,"items":[]}'},
  {role:'tool',tool_call_id:'multi',name,args:'{"action":"search","queries":["附件","解析"],"context":1}',content:'{"success":true,"hit_ordinals":[2],"context_truncated":false,"items":[]}'},
  {role:'tool',tool_call_id:'read',name,args:'{"action":"read","offset":200,"limit":2}',content:'{"success":true,"items":[{"ordinal":200,"source":{"paragraph":41}},{"ordinal":201,"source":{"paragraph":42}}]}'},
];
const labels=['搜索资料：附件','搜索资料：附件 / 解析','读取资料：第41–42段'];
beforeEach(()=>{
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);
  vi.stubGlobal('requestAnimationFrame',(callback:FrameRequestCallback)=>{callback(0);return 1;});
  host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals();});

test('restored Chat string arguments distinguish each action while details keep the actual tool name',async()=>{
  const original=JSON.stringify(history),items=historyItems(history);
  await act(async()=>root.render(<>{items.map(item=><Message key={item.id} item={item} owner="owner" onReuse={()=>{}}/>)}</>));
  const cards=[...host.querySelectorAll('.tool-card')];
  expect(cards).toHaveLength(3);
  cards.forEach((card,index)=>{
    expect(card.querySelector('summary')!.textContent).toContain(labels[index]);
    expect(card.querySelector('.tool-details code')!.textContent).toBe(name);
  });
  expect(cards[2].querySelector('summary')!.textContent).not.toContain('200');
  expect(cards[2].querySelector('.tool-details')!.textContent).toContain('"offset": 200');
  expect(JSON.stringify(history)).toBe(original);expect(items[0].args).toBe(history[0].args);
});

test('history trace uses the same labels in rows, timeline and details without changing kind or call totals',async()=>{
  const steps=withTraceHistory(historyItems(history),[]);
  await act(async()=>root.render(<TraceView steps={steps}/>));
  const rows=[...host.querySelectorAll<HTMLButtonElement>('.trace-row')];
  expect(rows.map(row=>row.querySelector('strong')!.textContent)).toEqual(labels);
  expect([...host.querySelectorAll('.trace-bar')].map(bar=>bar.getAttribute('aria-label'))).toEqual(labels.map(label=>`工具：${label}，已完成`));
  expect(host.querySelector('.trace-footer')!.textContent).toContain('3 条记录 · 3 个事件 · 已记录模型 0 次 · 工具 3 次');
  expect(steps.every(step=>step.kind==='tool'&&step.name===name&&step.tool_name===name)).toBe(true);
  await act(async()=>rows[2].click());
  expect(host.querySelector('.trace-details-heading strong')!.textContent).toBe(labels[2]);
  expect(host.querySelector('.trace-identifiers')!.textContent).toContain(name);
  expect(host.querySelector('.trace-tool-preview')!.textContent).toContain('paragraph');
  const search=host.querySelector<HTMLInputElement>('[aria-label="搜索轨迹"]')!;
  await act(async()=>{
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(search,'读取资料');
    search.dispatchEvent(new Event('input',{bubbles:true}));
  });
  expect(host.querySelectorAll('.trace-row')).toHaveLength(1);
  expect(host.querySelector('.trace-footer')!.textContent).toContain('工具 3 次');
});

test('live object arguments and malformed history retain safe labels and unchanged execution counts',async()=>{
  const items=historyItems([{role:'tool',tool_call_id:'broken',name,args:'{broken',content:'not-json'}]);
  const steps=[...withTraceHistory(items,[]),{id:'live',kind:'tool' as const,name,status:'running' as const,started_at:10,input:{action:'inspect'},attributes:{executed:true}}];
  await act(async()=>root.render(<TraceView steps={steps}/>));
  expect(host.querySelector('[data-trace-id="history:broken"] strong')!.textContent).toBe(name);
  expect(host.querySelector('[data-trace-id="live"] strong')!.textContent).toBe('查看资料结构');
  expect(host.querySelector('.trace-footer')!.textContent).toContain('2 条记录 · 2 个事件 · 已记录模型 0 次 · 工具 2 次');
  await act(async()=>host.querySelector<HTMLButtonElement>('[data-trace-id="live"]')!.click());
  expect(host.querySelector('.trace-identifiers')!.textContent).toContain(name);
});
