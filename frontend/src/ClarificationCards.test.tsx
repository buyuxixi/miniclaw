// @vitest-environment jsdom
import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {beforeEach,afterEach,test,expect,vi} from 'vitest';
import {ClarificationCards,hasPendingClarification} from './ClarificationCards';
import type {ChatController} from './chat-controller';
import type {ClarificationRequest} from './types';

let root:Root,host:HTMLDivElement;
const request:ClarificationRequest={id:'question',task_id:'task',version:2,status:'pending',deadline:2000000000,questions:[{id:'color',question:'选择颜色',choices:['红色','蓝色'],multi_select:false}]};
const button=(label:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>b.textContent===label)!;
const controller=()=>({connection:'open',state:{running:false,clarifications:[request]},answerClarification:vi.fn().mockResolvedValue(undefined),cancelClarification:vi.fn().mockResolvedValue(undefined),refreshClarifications:vi.fn().mockResolvedValue(undefined)}) as unknown as ChatController;
beforeEach(()=>{vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);localStorage.clear();host=document.createElement('div');document.body.append(host);root=createRoot(host);});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals();});

test('no option is preselected and a real answer carries a stable submission id',async()=>{
  const c=controller();await act(async()=>root.render(<ClarificationCards controller={c}/>));
  expect(host.querySelectorAll('input:checked')).toHaveLength(0);
  expect(button('回答并继续').disabled).toBe(true);
  await act(async()=>host.querySelector<HTMLInputElement>('input')!.click());
  expect(localStorage.getItem('miniclaw.clarification.question')).toContain('红色');
  await act(async()=>button('回答并继续').click());
  expect(c.answerClarification).toHaveBeenCalledWith(request,{color:'红色'},localStorage.getItem('miniclaw.clarification.question.submission'));
});

test('reloaded draft remains local and expired cards cannot submit it',async()=>{
  localStorage.setItem('miniclaw.clarification.question',JSON.stringify({color:'蓝色'}));
  const c=controller();await act(async()=>root.render(<ClarificationCards controller={c}/>));
  expect(host.querySelectorAll('input:checked')).toHaveLength(1);
  expect(c.answerClarification).not.toHaveBeenCalled();
  c.state.clarifications=[{...request,status:'timed_out'}];
  await act(async()=>root.render(<ClarificationCards controller={c}/>));
  expect(host.textContent).toContain('没有自动选择答案');
  expect(host.querySelector('textarea')).toBeNull();
  expect(c.answerClarification).not.toHaveBeenCalled();
});

test('revision and cancellation use task actions rather than answer text',async()=>{
  const c=controller();await act(async()=>root.render(<ClarificationCards controller={c}/>));
  await act(async()=>button('修改需求').click());
  expect(c.cancelClarification).toHaveBeenCalledWith(request,true);
  await act(async()=>button('取消任务').click());
  expect(c.cancelClarification).toHaveBeenCalledWith(request);
  expect(c.answerClarification).not.toHaveBeenCalled();
});

test('completed, canceled and superseded questions do not stay above the composer',async()=>{
  const c=controller();
  c.state.clarifications=[{...request,status:'answered',task_status:'completed',answers:{color:'蓝色'}},{...request,id:'old',status:'timed_out'}];
  await act(async()=>root.render(<ClarificationCards controller={c}/>));
  expect(host.textContent).toBe('');
  expect(host.querySelector('section')).toBeNull();
  expect(hasPendingClarification(c.state.clarifications)).toBe(false);
});

test('custom answer expands only when requested and a failed submission keeps the draft',async()=>{
  const c=controller();vi.mocked(c.answerClarification).mockRejectedValue(Error('连接中断'));
  await act(async()=>root.render(<ClarificationCards controller={c}/>));
  expect(host.querySelector('textarea')).toBeNull();
  await act(async()=>host.querySelector<HTMLInputElement>('[aria-label="其他，自己填写"]')!.click());
  const input=host.querySelector('textarea')!;
  await act(async()=>{
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(input,'深蓝色，保留原图');
    input.dispatchEvent(new Event('input',{bubbles:true}));
  });
  await act(async()=>button('回答并继续').click());
  expect(c.answerClarification).toHaveBeenCalledWith(request,{color:'深蓝色，保留原图'},expect.any(String));
  expect(host.querySelector('textarea')!.value).toBe('深蓝色，保留原图');
  expect(host.querySelector('[role="alert"]')!.textContent).toContain('连接中断');
});

test('multiple questions share one submit and navigation preserves the answers',async()=>{
  const c=controller();const multiple={...request,questions:[...request.questions,{id:'scope',question:'修改范围',choices:['局部','整图'],multi_select:false}]};
  c.state.clarifications=[multiple];
  await act(async()=>root.render(<ClarificationCards controller={c}/>));
  await act(async()=>host.querySelector<HTMLInputElement>('input')!.click());
  await act(async()=>button('下一题').click());
  expect(host.querySelector('h2')!.textContent).toBe('修改范围');
  expect(c.answerClarification).not.toHaveBeenCalled();
  await act(async()=>host.querySelector<HTMLInputElement>('input')!.click());
  await act(async()=>host.querySelector<HTMLButtonElement>('[aria-label="上一题"]')!.click());
  expect(host.querySelector<HTMLInputElement>('input')!.checked).toBe(true);
  await act(async()=>button('下一题').click());
  await act(async()=>button('回答并继续').click());
  expect(c.answerClarification).toHaveBeenCalledTimes(1);
  expect(c.answerClarification).toHaveBeenCalledWith(multiple,{color:'红色',scope:'局部'},expect.any(String));
});

test('multi select retains every selected option and disconnected state cannot submit',async()=>{
  const c=controller();c.state.clarifications=[{...request,questions:[{...request.questions[0],multi_select:true}]}];
  await act(async()=>root.render(<ClarificationCards controller={c}/>));
  const boxes=host.querySelectorAll<HTMLInputElement>('input[type="checkbox"]');
  await act(async()=>{boxes[0].click();boxes[1].click();});
  expect(host.querySelectorAll('input:checked')).toHaveLength(2);
  expect(JSON.parse(localStorage.getItem('miniclaw.clarification.question')!)).toEqual({color:['红色','蓝色']});
  Object.defineProperty(c,'connection',{value:'closed'});
  await act(async()=>root.render(<ClarificationCards controller={c}/>));
  expect(button('回答并继续').disabled).toBe(true);
  expect(c.answerClarification).not.toHaveBeenCalled();
});
