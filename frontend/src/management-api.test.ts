// @vitest-environment jsdom
import {afterEach,expect,test,vi} from 'vitest';
import {readApi} from './management-api';
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals();});
test('a caller-provided cancellation signal still has a network deadline',async()=>{
  const deadline=new AbortController(),caller=new AbortController();
  vi.spyOn(AbortSignal,'timeout').mockReturnValue(deadline.signal);
  vi.stubGlobal('fetch',vi.fn((_url,options)=>new Promise((_resolve,reject)=>{
    options.signal.addEventListener('abort',()=>reject(options.signal.reason),{once:true});
  })));
  const read=readApi('/api/miniclaw/skills',caller.signal);
  deadline.abort(new DOMException('read timed out','TimeoutError'));
  await expect(read).rejects.toHaveProperty('name','TimeoutError');
  expect(caller.signal.aborted).toBe(false);
});
test('closing a view immediately cancels its pending request',async()=>{
  const caller=new AbortController();
  vi.stubGlobal('fetch',vi.fn((_url,options)=>new Promise((_resolve,reject)=>{
    options.signal.addEventListener('abort',()=>reject(options.signal.reason),{once:true});
  })));
  const read=readApi('/api/miniclaw/skills',caller.signal);
  caller.abort();
  await expect(read).rejects.toHaveProperty('name','AbortError');
});
