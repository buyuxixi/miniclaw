import {expect,test} from 'vitest';
import {documentToolLabel} from './tool-label';
import {traceStepLabel,traceSummary,type TraceStep} from './trace-view';

const name='miniclaw_document_query';

test('search labels accept one query or bounded query arrays in objects and JSON strings',()=>{
  expect(documentToolLabel(name,{action:'search',query:'附件'})).toBe('搜索资料：附件');
  expect(documentToolLabel(name,JSON.stringify({action:'search',queries:['附件','解析'],context:2}))).toBe('搜索资料：附件 / 解析');
  expect(documentToolLabel(name,{action:'search',queries:[null,2,'  附件\n 上传  ']})).toBe('搜索资料：附件 上传');
  expect(documentToolLabel(name,{action:'search'})).toBe('搜索资料');
  const label=documentToolLabel(name,{action:'search',queries:Array.from({length:20},()=>'<script>'+('词'.repeat(500)))});
  expect(label.length).toBeLessThanOrEqual(120);expect(label.endsWith('…')).toBe(true);
});

test('read labels use actual returned paragraph sources and preserve gaps',()=>{
  const result={success:true,items:[{ordinal:200,source:{paragraph:4}},{ordinal:201,source:{paragraph:5}},{ordinal:202,source:{paragraph:7}}]};
  expect(documentToolLabel(name,{action:'read',offset:200,limit:3},JSON.stringify(result))).toBe('读取资料：第4–5段 / 第7段');
  expect(documentToolLabel(name,{action:'read',offset:200,limit:3})).toBe('读取资料');
  expect(documentToolLabel(name,{action:'read',offset:200,limit:3},{items:[{ordinal:200},{ordinal:201}]})).toBe('读取资料');
});

test('page and line ranges include only returned locations and keep table scope',()=>{
  expect(documentToolLabel(name,{action:'read'},{items:[{source:{page:2}},{source:{page:4}}]})).toBe('读取资料：第2页 / 第4页');
  expect(documentToolLabel(name,{action:'read'},{items:[{source:{line_start:70,line_end:73}},{source:{line_start:74,line_end:76}}]})).toBe('读取资料：第70–76行');
  expect(documentToolLabel(name,{action:'read'},{items:[{source:{sheet:'销售明细',row_number:3}},{source:{sheet:'销售明细',row_number:4}},{source:{sheet:'退款',row_number:3}}]})).toBe('读取资料：销售明细 第3–4行 / 退款 第3行');
  expect(documentToolLabel(name,{action:'read'},{source:{page:9}})).toBe('读取资料：第9页');
  expect(documentToolLabel(name,{action:'read'},{items:[{source:{page:-1,paragraph:0,line_start:'3'}}]})).toBe('读取资料');
});

test('known actions have concrete labels and malformed or unknown actions retain the tool name',()=>{
  expect(documentToolLabel(name,{action:'inspect'})).toBe('查看资料结构');
  expect(documentToolLabel(name,'{"action":"calculate"}')).toBe('计算资料');
  expect(documentToolLabel(name,{action:'analysis_status'})).toBe('查看分析进度');
  for(const args of [null,[],2,'{broken','x'.repeat(128001),{action:'new_action'}])expect(documentToolLabel(name,args)).toBe(name);
  expect(documentToolLabel(name,{get action(){throw new Error('unreadable');}})).toBe(name);
  expect(documentToolLabel('another_tool',{action:'search',query:'附件'})).toBe('another_tool');
});

test('trace labels and model tool-call summaries reuse the helper without modifying steps',()=>{
  const step:TraceStep={id:'tool',kind:'tool',name,tool_name:name,status:'completed',input:'{"action":"search","queries":["附件","解析"]}'};
  expect(traceStepLabel(step)).toBe('搜索资料：附件 / 解析');expect(step.name).toBe(name);
  expect(traceStepLabel({...step,kind:'model'})).toBe(name);
  expect(traceSummary({...step,kind:'model',output:{tool_calls:[{function:{name,arguments:step.input}},{function:{name,arguments:'{"action":"read","offset":9}'}}]}})).toBe('调用工具：搜索资料：附件 / 解析、读取资料');
});
