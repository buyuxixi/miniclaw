// @vitest-environment jsdom
import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,test,vi} from 'vitest';
import {TraceView,type TraceViewProps} from './TraceView';
import {formatTraceDuration,traceDuration,traceReadingRows,traceRoundKey,traceSpan,traceSummary,type TraceStep} from './trace-view';

let root:Root,host:HTMLDivElement;
const steps:TraceStep[]=[
  {id:'input-1',kind:'input',name:'用户请求',status:'completed',started_at:1720000000,ended_at:1720000000,content:'读取文档，整理结果',turn_id:'turn-1',turn_index:1},
  {id:'model-1',kind:'model',name:'DeepSeek 请求',status:'failed',started_at:1720000000,ended_at:1720000002,provider:'deepseek',model:'deepseek-flash',request_id:'request-1',attempt:1,error:'余额不足',turn_id:'turn-1',input_tokens:null,output_tokens:null},
  {id:'recovery-1',kind:'recovery',name:'切换备用模型',status:'completed',started_at:1720000002,ended_at:1720000002,summary:'主服务额度不足，使用百炼',turn_id:'turn-1',attributes:{reason:'billing',budget:{requests:1}}},
  {id:'model-2',kind:'model',name:'百炼请求',status:'completed',started_at:1720000002,ended_at:1720000005,provider:'bailian',model:'qwen-plus',request_id:'request-2',attempt:1,input_tokens:31,output_tokens:8,turn_id:'turn-1',task_id:'task-1',session_id:'session-1',content:'<script>window.traceUnsafe=true</script>建议读取文档'},
  {id:'tool-1',kind:'tool',name:'读取文档',tool_name:'read_file',status:'unknown',started_at:1720000005,ended_at:1720000006,operation_id:'operation-1',turn_id:'turn-1',input:{path:'C:/工作区/'+('long/'.repeat(100))+'说明.txt'},output:{error:'结果未知',outcome_uncertain:true}},
];
const button=(label:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(item=>item.textContent===label)!;
const row=(id:string)=>host.querySelector<HTMLButtonElement>(`[data-trace-id="${id}"]`)!;
async function render(props:Partial<TraceViewProps>={}) {await act(async()=>root.render(<TraceView steps={steps} {...props}/>));}
async function changeInput(value:string) {const input=host.querySelector<HTMLInputElement>('[aria-label="搜索轨迹"]')!;await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,value);input.dispatchEvent(new Event('input',{bubbles:true}));});}
beforeEach(()=>{vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubGlobal('requestAnimationFrame',(callback:FrameRequestCallback)=>{callback(0);return 1;});host=document.createElement('div');document.body.append(host);root=createRoot(host);});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals();});

test('shows the three lanes and only recorded token usage',async()=>{
  await render({running:true});
  expect(host.querySelectorAll('.trace-lane')).toHaveLength(3);
  expect(host.querySelectorAll('.trace-bar')).toHaveLength(5);
  expect(host.querySelectorAll('.trace-row')).toHaveLength(5);
  expect(host.querySelector('.trace-footer')!.textContent).toContain('5 条记录 · 5 个事件 · 已记录模型 2 次 · 工具 1 次');
  expect(host.querySelector('.trace-footer')!.textContent).toContain('39 Token');
  expect(host.querySelector('[role="status"]')!.textContent).toBe('实时记录中');
  expect(host.querySelector('.trace-details')).toBeNull();
});

test('selecting a request reveals exact metrics, preview and safely escaped raw content',async()=>{
  await render();await act(async()=>row('model-2').click());
  expect(host.querySelector('.trace-details')!.textContent).toContain('request-2');
  expect(host.querySelector('.trace-details')!.textContent).toContain('qwen-plus');
  expect(host.querySelector('.trace-details')!.textContent).toContain('task-1');
  expect(host.querySelector('.trace-details')!.textContent).toContain('session-1');
  expect(host.querySelector('.trace-details')!.textContent).toContain('3.00 秒');
  await act(async()=>button('预览').click());
  expect(host.querySelector('.trace-detail-body')!.textContent).toContain('<script>window.traceUnsafe=true</script>');
  expect(host.querySelector('script')).toBeNull();
  await act(async()=>button('原始内容').click());
  expect(host.querySelector('.trace-raw')!.textContent).toContain('"input_tokens": 31');
  expect(host.querySelector('.trace-raw')!.textContent).toContain('request-2');
  await act(async()=>host.querySelector<HTMLButtonElement>('[aria-label="关闭步骤详情"]')!.click());
  expect(host.querySelector('.trace-details')).toBeNull();
  expect(document.activeElement).toBe(row('model-2'));
});

test('timeline selection locates the matching row and recovery reason remains inspectable',async()=>{
  await render();const scroll=vi.fn();row('recovery-1').scrollIntoView=scroll;
  await act(async()=>host.querySelector<HTMLButtonElement>('[aria-label="恢复：切换备用模型，已完成"]')!.click());
  expect(scroll).toHaveBeenCalledWith({block:'nearest',behavior:'auto'});
  expect(row('recovery-1').getAttribute('aria-pressed')).toBe('true');
  expect(host.querySelector('.trace-details')!.textContent).toContain('billing');
  expect(host.querySelector('.trace-details')!.textContent).toContain('requests');
});

test('search and status filtering do not alter execution totals or retain hidden detail',async()=>{
  await render();await act(async()=>row('model-2').click());await changeInput('余额不足');
  expect(host.querySelectorAll('.trace-row')).toHaveLength(1);
  expect(row('model-1')).toBeTruthy();expect(host.querySelector('.trace-details')).toBeNull();
  expect(host.querySelector('.trace-footer')!.textContent).toContain('5 个事件');
  await changeInput('');const select=host.querySelector<HTMLSelectElement>('[aria-label="筛选轨迹状态"]')!;
  await act(async()=>{select.value='unknown';select.dispatchEvent(new Event('change',{bubbles:true}));});
  expect(host.querySelectorAll('.trace-row')).toHaveLength(1);expect(row('tool-1')).toBeTruthy();
  await changeInput('找不到');expect(host.textContent).toContain('没有匹配的步骤');
  await act(async()=>button('清除筛选').click());expect(host.querySelectorAll('.trace-row')).toHaveLength(5);
});

test('history with no timestamps does not fabricate a duration or token count',async()=>{
  await render({steps:[{id:'history',kind:'assistant',name:'助手回复',status:'completed',content:'历史回复',source:'history',started_at:null,ended_at:null,input_tokens:null,output_tokens:null}]});
  expect(button('时长').disabled).toBe(true);expect(button('调用').getAttribute('aria-pressed')).toBe('true');
  expect(button('轮次').disabled).toBe(true);
  expect(host.querySelector('.trace-footer')!.textContent).not.toContain('Token');
  await act(async()=>row('history').click());expect(host.querySelector('.trace-details')!.textContent).toContain('未记录');
  expect(host.querySelector('.trace-details')!.textContent).not.toContain('0 毫秒');
});

test('keyboard navigation and Escape preserve a usable inspection flow',async()=>{
  await render();row('input-1').focus();
  await act(async()=>row('input-1').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true})));
  expect(document.activeElement).toBe(row('model-1'));
  await act(async()=>row('model-1').dispatchEvent(new KeyboardEvent('keydown',{key:'End',bubbles:true})));
  expect(document.activeElement).toBe(row('tool-1'));
  await act(async()=>row('tool-1').click());
  expect(document.activeElement!.getAttribute('aria-label')).toBe('关闭步骤详情');
  await act(async()=>document.activeElement!.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})));
  expect(host.querySelector('.trace-details')).toBeNull();expect(document.activeElement).toBe(row('tool-1'));
});

test('refresh failure retains previous steps and paging is explicitly controlled by the host',async()=>{
  const onRefresh=vi.fn(),onLoadMore=vi.fn();await render({error:'连接中断',onRefresh,hasMore:true,onLoadMore});
  expect(host.querySelector('[role="alert"]')!.textContent).toContain('连接中断');expect(host.querySelectorAll('.trace-row')).toHaveLength(5);
  await act(async()=>button('重新加载').click());await act(async()=>button('加载更早的步骤').click());
  expect(onRefresh).toHaveBeenCalledTimes(1);expect(onLoadMore).toHaveBeenCalledTimes(1);
  await render({loading:true,hasMore:true,onLoadMore});expect(button('正在读取…').disabled).toBe(true);
});

test('loading, empty and running states explain when steps will appear',async()=>{
  await render({steps:[],loading:true});expect(host.textContent).toContain('正在读取轨迹');
  expect(host.textContent).not.toContain('还没有执行轨迹');expect(host.querySelector('.trace-footer')!.textContent).toBe('正在同步…');
  expect(host.querySelector('.trace-footer')!.textContent).not.toContain('0 步');expect(host.querySelector('.trace-footer')!.textContent).not.toContain('模型 0 次');
  await render({steps:[]});expect(host.textContent).toContain('还没有执行轨迹');
  await render({steps:[],running:true});expect(host.textContent).toContain('正在记录执行过程');
});

test('long arguments, uncertain effects and appended steps remain selectable',async()=>{
  await render();await act(async()=>row('tool-1').click());await act(async()=>button('预览').click());
  expect(host.querySelector('.trace-detail-body')!.textContent).toContain('说明.txt');expect(host.querySelector('.trace-detail-body')!.textContent).toContain('outcome_uncertain');
  await render({steps:[...steps,{id:'task-1',kind:'task',name:'等待核对',status:'waiting'}],running:true});
  expect(row('tool-1').getAttribute('aria-pressed')).toBe('true');expect(host.querySelectorAll('.trace-row')).toHaveLength(6);
});

test('mode controls and helper durations use only recorded facts',async()=>{
  await render();await act(async()=>button('轮次').click());expect(button('轮次').getAttribute('aria-pressed')).toBe('true');
  await act(async()=>button('调用').click());expect(button('调用').getAttribute('aria-pressed')).toBe('true');
  expect(traceDuration(steps[1])).toBe(2000);expect(traceSpan(steps)!.duration).toBe(6000);
  expect(formatTraceDuration(null)).toBe('未记录');expect(formatTraceDuration(61200)).toBe('1 分 1 秒');
});

test('narrow detail drawer keeps Tab inside and Escape returns to the selected step',async()=>{
  vi.stubGlobal('matchMedia',()=>({matches:true,addEventListener:vi.fn(),removeEventListener:vi.fn()}));
  await render();await act(async()=>row('tool-1').click());
  const drawer=host.querySelector<HTMLElement>('[role="dialog"]')!,close=host.querySelector<HTMLButtonElement>('[aria-label="关闭步骤详情"]')!,panel=host.querySelector<HTMLElement>('[role="tabpanel"]')!;
  expect(drawer.getAttribute('aria-modal')).toBe('true');
  close.focus();await act(async()=>close.dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',shiftKey:true,bubbles:true,cancelable:true})));
  expect(document.activeElement).toBe(panel);
  await act(async()=>panel.dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',bubbles:true,cancelable:true})));
  expect(document.activeElement).toBe(close);
  await act(async()=>close.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})));
  expect(host.querySelector('[role="dialog"]')).toBeNull();expect(document.activeElement).toBe(row('tool-1'));
});

test('receipt reuse and waiting for confirmation do not count as tool executions',async()=>{
  await render({steps:[...steps,
    {id:'receipt',kind:'tool',name:'复用已保存结果',status:'completed',started_at:1720000007,attributes:{executed:false,disposition:'reuse'}},
    {id:'confirm',kind:'tool',name:'等待确认',status:'waiting',started_at:1720000008,attributes:{executed:false}},
    {id:'prepared',kind:'tool',name:'准备调用',status:'running'},
    {id:'historical-tool',kind:'tool',name:'历史工具结果',status:'completed',source:'history'},
  ]});
  expect(host.querySelector('.trace-footer')!.textContent).toContain('9 条记录 · 9 个事件 · 已记录模型 2 次 · 工具 2 次');
});

test('task events without a recorded round stay in one unknown task group',async()=>{
  const mixed:TraceStep[]=[
    {id:'request',kind:'model',name:'模型请求',status:'completed',turn_id:'actual-turn',task_id:'task-1'},
    {id:'unknown-task',kind:'task',name:'任务状态',status:'completed',task_id:'task-1'},
    {id:'unknown-recovery',kind:'recovery',name:'恢复记录',status:'completed',task_id:'task-1'},
  ];
  await render({steps:mixed});await act(async()=>button('轮次').click());
  const bars=host.querySelectorAll<HTMLButtonElement>('.trace-bar');
  expect(bars[0].style.left).toBe('0%');expect(bars[0].style.width).toBe('50%');
  expect(bars).toHaveLength(2);expect(bars[1].style.left).toBe('75%');expect(bars[1].style.width).toBe('25%');
  expect(traceRoundKey(mixed[1])).toBe(traceRoundKey(mixed[2]));
  expect(traceRoundKey({...mixed[1],task_id:null})).toBe('unknown');
  await act(async()=>row('unknown-task').click());expect(host.querySelector('.trace-identifiers')!.textContent).toContain('轮次未记录');
});

test('task spans stay out of the lanes and public assistant content remains a point marker',async()=>{
  await render({steps:[...steps,{id:'task-span',kind:'task',name:'任务完成',status:'completed',started_at:1720000000,ended_at:1720000006},{id:'assistant-span',kind:'assistant',name:'助手回复',status:'completed',started_at:1720000002,ended_at:1720000006,content:'已读取文档'}]});
  expect(host.querySelector('.trace-bar-task')).toBeNull();expect(row('task-span')).toBeTruthy();
  expect(host.querySelector<HTMLElement>('.trace-bar-assistant')!.style.width).toBe('0.3%');
});

test('model summaries prefer public text or tool names while detail keeps the raw response',async()=>{
  const response={content:'',tool_calls:[{function:{name:'read_file',arguments:'{"path":"说明.txt"}'}}],usage:{input_tokens:31,output_tokens:8}};
  const model={...steps[3],content:null,summary:JSON.stringify(response),output:response};
  expect(traceSummary(model)).toBe('调用工具：read_file');
  expect(traceSummary({...model,content:'公开的模型回复'})).toBe('公开的模型回复');
  expect(traceSummary({...model,output:{...response,content:'输出中的公开正文'}})).toBe('输出中的公开正文');
  await render({steps:[model]});expect(row('model-2').textContent).toContain('调用工具：read_file');expect(row('model-2').textContent).not.toContain('input_tokens');
  await act(async()=>row('model-2').click());
  const metricLabels=[...host.querySelectorAll('.trace-metrics dt')].map(item=>item.textContent);
  expect(metricLabels.indexOf('输出 Token')).toBeLessThan(metricLabels.indexOf('任务 ID'));
  expect(metricLabels.indexOf('服务')).toBeLessThan(metricLabels.indexOf('请求 ID'));
  await act(async()=>button('原始内容').click());expect(host.querySelector('.trace-raw')!.textContent).toContain('tool_calls');expect(host.querySelector('.trace-raw')!.textContent).toContain('input_tokens');
});

test('tool overview puts brief arguments and result before engineering identifiers',async()=>{
  const tool={...steps[4],input:{path:'说明.txt'},output:{content:'文档内容已读取，包含时间范围和统计信息'},task_id:'very-long-task-id',session_id:'very-long-session-id',request_id:'request-id'};
  await render({steps:[tool]});await act(async()=>row('tool-1').click());
  const overview=host.querySelector('.trace-detail-body')!,text=overview.textContent!;
  expect(text).toContain('参数摘要');expect(text).toContain('说明.txt');expect(text).toContain('结果摘要');expect(text).toContain('文档内容已读取');
  expect(text.indexOf('文档内容已读取')).toBeLessThan(text.indexOf('very-long-task-id'));
  expect(text.indexOf('结果摘要')).toBeLessThan(text.indexOf('参数摘要'));
  expect(overview.querySelectorAll('.trace-tool-preview')).toHaveLength(2);
  expect(overview.querySelectorAll('.trace-tool-preview pre')[1].textContent).toBe('{"path":"说明.txt"}');
  expect(overview.querySelector('.trace-metrics')!.textContent).not.toContain('来源');
  expect(overview.querySelector('.trace-metrics')!.textContent).not.toContain('开始时间');
  expect(overview.querySelector('.trace-identifiers')!.textContent).toContain('very-long-session-id');
});

function recordedConversation():TraceStep[] {
  return [
    {id:'task',kind:'task',name:'任务执行',status:'completed',sequence:1,task_id:'task',started_at:1,ended_at:6,summary:'最终回复'},
    {id:'user',kind:'input',name:'用户输入',status:'completed',sequence:2,task_id:'task',started_at:1,content:'请读取根目录'},
    {id:'context',kind:'context',name:'本轮应用上下文',status:'completed',sequence:3,task_id:'task',started_at:1.1,content:'本轮澄清规则：只读，不执行收费生成。'},
    {id:'request-1',kind:'model',name:'模型请求',status:'completed',sequence:4,task_id:'task',started_at:2,ended_at:3,provider:'deepseek',model:'deepseek-flash',input_tokens:20,output_tokens:3,output:{tool_calls:[{function:{name:'list_files'}}]}},
    {id:'call',kind:'assistant',name:'助手调用工具',status:'completed',sequence:5,task_id:'task',started_at:3,summary:'list_files',attributes:{model_step_id:'request-1'}},
    {id:'tool',kind:'tool',name:'list_files',status:'completed',sequence:6,task_id:'task',started_at:3.1,ended_at:4,tool_name:'list_files',input:{path:'.'},output:{success:true,entries:[{name:'a.md'},{name:'b.txt'}]},attributes:{executed:true}},
    {id:'request-2',kind:'model',name:'模型请求',status:'completed',sequence:7,task_id:'task',started_at:4,ended_at:5,provider:'deepseek',model:'deepseek-flash',output:{content:'最终回复'}},
    {id:'reply',kind:'assistant',name:'助手回复',status:'completed',sequence:8,task_id:'task',started_at:5,content:'最终回复',attributes:{model_step_id:'request-2'}},
  ];
}

test('default reading order starts with the user and shows each public response once',async()=>{
  await render({steps:recordedConversation().reverse()});
  expect([...host.querySelectorAll('.trace-row')].map(item=>item.getAttribute('data-trace-id'))).toEqual(['user','context','call','tool','reply','task']);
  expect(host.querySelector('.trace-list')!.textContent!.match(/最终回复/g)).toHaveLength(1);
  expect(row('task').textContent).not.toContain('最终回复');
  expect(row('context').classList.contains('trace-row-context')).toBe(true);
  expect(row('user').textContent).toContain('第 1 轮');
  expect(row('user').querySelector('time')!.textContent).not.toBe('—');
  expect(row('context').querySelector('time')!.textContent).not.toBe('—');
  expect(row('tool').textContent).toContain('{"path":"."} → 2 个条目：a.md、b.txt');
  expect(host.querySelector('.trace-footer')!.textContent).toContain('6 条记录 · 8 个事件 · 已记录模型 2 次 · 工具 1 次');
  await act(async()=>button('全部事件').click());
  expect([...host.querySelectorAll('.trace-row')].map(item=>item.getAttribute('data-trace-id'))).toEqual(['user','context','request-1','call','tool','request-2','reply','task']);
});

test('a hidden physical request remains inspectable through its message and timeline',async()=>{
  await render({steps:recordedConversation()});
  await act(async()=>row('call').click());
  expect(host.querySelector('.trace-details')!.textContent).toContain('deepseek-flash');
  expect(host.querySelector('.trace-details')!.textContent).toContain('模型耗时1.00 秒');
  await act(async()=>button('查看模型请求 · deepseek-flash').click());
  expect(row('call').getAttribute('aria-pressed')).toBe('true');
  await act(async()=>button('原始内容').click());
  expect(host.querySelector('.trace-raw')!.textContent).toContain('"id": "request-1"');
  await act(async()=>host.querySelector<HTMLButtonElement>('[aria-label="关闭步骤详情"]')!.click());
  expect(document.activeElement).toBe(row('call'));
  await changeInput('deepseek');
  expect([...host.querySelectorAll('.trace-row')].map(item=>item.getAttribute('data-trace-id'))).toEqual(['call','reply']);
  await act(async()=>host.querySelectorAll<HTMLButtonElement>('.trace-bar-model')[1].click());
  expect(row('reply').getAttribute('aria-pressed')).toBe('true');
  expect(host.querySelector('.trace-details')!.textContent).toContain('模型请求');
});

test('reading keeps failed attempts and settles each resumed span before the next user',()=>{
  const first=recordedConversation();
  const second:TraceStep[]=[
    {id:'resume-task',kind:'task',name:'任务继续',status:'failed',sequence:9,task_id:'task',ended_at:10},
    {id:'answer',kind:'input',name:'继续任务',status:'completed',sequence:10,task_id:'task',content:'继续'},
    {id:'failed',kind:'model',name:'模型请求',status:'failed',sequence:11,task_id:'task',error:'超时',attempt:1},
    {id:'retry',kind:'recovery',name:'准备重试',status:'completed',sequence:12,task_id:'task',attributes:{action:'retry',reason:'timeout'}},
    {id:'retry-failed',kind:'model',name:'模型请求',status:'failed',sequence:13,task_id:'task',error:'超时',attempt:2},
  ];
  const rows=traceReadingRows([...first,...second]);
  expect(rows.map(({step})=>step.id)).toEqual(['user','context','call','tool','reply','task','answer','failed','retry','retry-failed','resume-task']);
  expect(rows.find(({step})=>step.id==='answer')!.round).toBe(2);
  const historical:TraceStep={id:'old',kind:'input',name:'旧消息',status:'completed',source:'history',content:'旧问题'};
  expect(traceReadingRows([historical,...first])[0].step.id).toBe('old');
  expect(traceReadingRows([historical,...first]).find(({step})=>step.id==='user')!.round).toBe(2);
});
