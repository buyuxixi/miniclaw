// @vitest-environment jsdom
import {act} from 'react';
import {createRoot} from 'react-dom/client';
import {afterEach,beforeEach,expect,test,vi} from 'vitest';
import {plansByMessage,fullImagePlanPrompt,clarification} from './director-conversation';
import {DirectorQuestions} from './DirectorQuestions';
import {ImagePlanPanel,type ImagePlan} from './ImagePlanPanel';
import {Message} from './Message';
import type {Project} from './canvas-api';
import type {ChatItem} from './types';
import {readApi,writeApi} from './management-api';
vi.mock('./management-api',()=>({readApi:vi.fn(),writeApi:vi.fn()}));
(globalThis as any).IS_REACT_ACT_ENVIRONMENT=true;
const plan=(id:string):ImagePlan=>({id,project:'precision',revision:1,input_revision:1,layer_id:'image',goal:'眼角旁添加小痣',preserve:'五官、肤色与背景',state:'proposed',steps:[{action:'ai_edit',label:'添加小痣',params:{prompt:'在画面右侧眼角添加一颗浅褐色小痣。',region:false}}]});
const proposal=(id:string):ChatItem=>({id:'tool-'+id,kind:'tool',name:'miniclaw_canvas_propose',text:'',result:JSON.stringify({success:true,id,project:'precision'})});
let host:HTMLDivElement,root:ReturnType<typeof createRoot>;
beforeEach(()=>{vi.clearAllMocks();host=document.createElement('div');document.body.append(host);root=createRoot(host);});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();});

test('two proposals remain attached to their own replies as later conversation continues',()=>{
  const items:ChatItem[]=[{id:'u1',kind:'user',text:'眼角加痣'},proposal('one'),{id:'a1',kind:'assistant',text:'第一份方案'}, {id:'u2',kind:'user',text:'浅一点'},proposal('two'),{id:'a2',kind:'assistant',text:'第二份方案'},{id:'u3',kind:'user',text:'先聊一下'}, {id:'a3',kind:'assistant',text:'请告诉我哪里不满意'}];
  const grouped=plansByMessage(items,[plan('one'),plan('two')]);
  expect([...grouped.keys()]).toEqual(['a1','a2']);expect(grouped.get('a1')?.map(p=>p.id)).toEqual(['one']);
  expect(grouped.get('a2')?.map(p=>p.id)).toEqual(['two']);
});
test('missing replies attach to the actual tool and never cross the next user turn',()=>{
  const items:ChatItem[]=[proposal('one'),{id:'u2',kind:'user',text:'下一轮'},{id:'a2',kind:'assistant',text:'下一轮回复'}];
  expect([...plansByMessage(items,[plan('one')]).keys()]).toEqual(['tool-one']);
});
test('read tools, failed proposals, foreign project ids and malformed results cannot claim a plan',()=>{
  const source=proposal('one');
  for(const item of [{...source,name:'miniclaw_canvas_view'},{...source,result:{success:false,id:'one',project:'precision'}},{...source,result:{success:true,id:'one',project:'foreign'}},{...source,result:'partial-json'}])expect(plansByMessage([item],[plan('one')]).size).toBe(0);
});
test('only a complete full-image AI plan can refill a prompt, preserving all confirmed text',()=>{
  const p=plan('one');expect(fullImagePlanPrompt(p)).toBe('在画面右侧眼角添加一颗浅褐色小痣。\n必须保留：五官、肤色与背景');
  expect(fullImagePlanPrompt({...p,steps:[{...p.steps[0],params:{prompt:'局部修改',region:true}}]})).toBeNull();
  expect(fullImagePlanPrompt({...p,steps:[{action:'flip',label:'翻转',params:{}},...p.steps]})).toBeNull();
  expect(fullImagePlanPrompt({...p,preserve:'x'.repeat(2000)})).toBeNull();
});
test('clarification accepts bounded questions and never treats extra action fields as instructions',()=>{
  const data={questions:[{title:'哪里不满意？',options:['位置','程度']}]};const block=(v:unknown)=>'```studio-question\n'+JSON.stringify(v)+'\n```';
  expect(clarification('先确认一下。\n'+block(data))).toEqual({body:'先确认一下。',questions:data.questions});
  for(const bad of [{...data,execute:true},{questions:[]},{questions:[{title:'x',options:['同一个','同一个']}]},{questions:Array(4).fill(data.questions[0])}])expect(clarification(block(bad))).toBeNull();
  expect(clarification(block(data)+block(data))).toBeNull();
});
test('answers support choices and free text, survive rejection and submit only once after success',async()=>{
  const answer=vi.fn().mockResolvedValueOnce(false).mockResolvedValueOnce(true);
  await act(async()=>root.render(<DirectorQuestions questions={[{title:'哪里不满意？',options:['位置','程度']},{title:'希望怎样调整？',options:['浅一点','小一点']}]} disabled={false} onAnswer={answer}/>));
  const button=(text:string)=>[...host.querySelectorAll('button')].find(b=>b.textContent===text)!;
  await act(async()=>button('位置').click());expect(answer).not.toHaveBeenCalled();
  const input=host.querySelectorAll('input')[1];
  await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,'位置往外移一点');input.dispatchEvent(new Event('input',{bubbles:true}));});
  await act(async()=>host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  expect(answer).toHaveBeenCalledWith('哪里不满意？\n位置\n\n希望怎样调整？\n位置往外移一点');
  expect(input.value).toBe('位置往外移一点');expect(host.textContent).toContain('回答已保留');
  await act(async()=>host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  expect(host.textContent).toContain('已回答');expect(host.querySelector('fieldset')?.disabled).toBe(true);
  await act(async()=>host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  expect(answer).toHaveBeenCalledTimes(2);
});
test('clarification renders inside its assistant reply without exposing the schema',async()=>{
  await act(async()=>root.render(<Message item={{id:'a',kind:'assistant',status:'done',text:'先确认问题。\n```studio-question\n{"questions":[{"title":"哪里不满意？","options":["位置","程度"]}]}\n```'}} owner="owner" onReuse={()=>{}} onAnswer={vi.fn()} answerDisabled/>));
  expect(host.querySelector('article.assistant .director-questions')).not.toBeNull();expect(host.textContent).not.toContain('studio-question');expect(host.querySelector('fieldset')?.disabled).toBe(true);
});
test('controlled AI plan offers refill without choosing a hidden model or generating',async()=>{
  const fill=vi.fn().mockResolvedValue(undefined);
  await act(async()=>root.render(<ImagePlanPanel project={{id:'precision',revision:1} as Project} plans={[plan('one')]} busy={false} canPlan hasTarget compact onSend={vi.fn()} onRun={async work=>work()} onRefresh={vi.fn()} onFillPrompt={fill}/>));
  const action=[...host.querySelectorAll('button')].find(b=>b.textContent==='回填画布，选择模型')!;
  await act(async()=>action.click());expect(fill).toHaveBeenCalledWith(plan('one'));
  expect(readApi).not.toHaveBeenCalled();expect(writeApi).not.toHaveBeenCalled();
  expect(host.textContent).not.toContain('生成AI候选 · 可能计费');
});

test('opening the same clarification in full Chat shows readable questions instead of internal JSON',async()=>{
  await act(async()=>root.render(<Message item={{id:'a',kind:'assistant',text:'先确认。\n```studio-question\n{"questions":[{"title":"哪里不满意？","options":["位置","程度"]}]}\n```'}} owner="owner" onReuse={()=>{}}/>));
  expect(host.textContent).toContain('哪里不满意？');expect(host.textContent).toContain('位置 / 程度');expect(host.textContent).not.toContain('studio-question');
});

test('streaming questions do not expose an unfinished internal schema',async()=>{
  await act(async()=>root.render(<Message item={{id:'a',kind:'assistant',status:'running',text:'先确认一下。\n```studio-question\n{"questions":[{"title":"哪里不满'}} owner="owner" onReuse={()=>{}} onAnswer={vi.fn()}/>));
  expect(host.textContent).toContain('先确认一下。');expect(host.textContent).not.toContain('studio-question');expect(host.textContent).not.toContain('questions');
});

test('the last successful proposal in one reply is shown before earlier versions',()=>{
  const grouped=plansByMessage([proposal('one'),proposal('two'),{id:'reply',kind:'assistant',text:'这一轮的方案'}],[plan('one'),plan('two')]);
  expect(grouped.get('reply')?.map(p=>p.id)).toEqual(['two','one']);
});
