import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {expect,test} from 'vitest';

function workbench(overrides={}){
  const saved=new Map(),frames=new Map();let frame=0;
  const context={crypto:{randomUUID:()=> 'fixture-id'},URLSearchParams,AbortSignal,location:{search:'?workspace=fixture',origin:'http://localhost'},
    localStorage:{getItem:k=>saved.get(k)||null,setItem:(k,v)=>saved.set(k,v),removeItem:k=>saved.delete(k)},sessionStorage:{getItem:()=>null,setItem(){},removeItem(){}},
    setTimeout:()=>1,clearTimeout(){},setInterval(){},matchMedia:()=>({matches:false}),
    requestAnimationFrame:cb=>{frames.set(++frame,cb);return frame;},cancelAnimationFrame:id=>frames.delete(id)};
  Object.assign(context,overrides);context.window=context;
  for(const name of ['project-name','usability','workflow','app','integration','production','node-composer','interaction'])runInNewContext(readFileSync(new URL('../public/studio/'+name+'.js',import.meta.url),'utf8'),context);
  const app=context.film();app.workspaceId='fixture';app.projectReady=false;
  const world={style:{}};app.$refs={world:{clientWidth:1200,clientHeight:800,querySelector:()=>world,getBoundingClientRect:()=>({left:0,top:0})}};
  return {app,saved,frames,world,context,flush:()=>{const callbacks=[...frames.values()];frames.clear();callbacks.forEach(cb=>cb());}};
}

test('selecting nodes leaves the viewport stable and only explicit expansion reveals controls',()=>{
  const {app}=workbench();const before=JSON.stringify(app.shots);const pan={...app.pan};
  app.choose('s1');expect(app.composerTask).toBe('video');expect(app.composerExpanded).toBe(false);expect(app.pan).toEqual(pan);
  let reveals=0;app.$nextTick=fn=>fn();app.revealComposerTarget=()=>reveals++;
  app.toggleComposer();expect(app.composerExpanded).toBe(true);expect(reveals).toBe(1);
  app.choose('s2');expect(app.composerExpanded).toBe(false);expect(reveals).toBe(1);
  expect(JSON.stringify(app.shots)).toBe(before);
  app.toggleComposer();app.clearCanvasSelection();expect(app.composerExpanded).toBe(false);expect(app.composerTask).toBe('');
});

test('upward model menus keep an eight pixel gap for short and scrollable lists',()=>{
  const {app}=workbench({innerWidth:1000,innerHeight:800});
  const trigger={getBoundingClientRect:()=>({left:300,top:550,bottom:584})};
  const style=app.popupStyle(trigger,320,400);
  // CSS bottom anchoring must use the rendered height, not the maximum height.
  for(const renderedHeight of [270,400]){
    const top=style.top==='auto'?800-parseFloat(style.bottom)-renderedHeight:parseFloat(style.top);
    expect(550-(top+renderedHeight)).toBe(8);
  }
  expect(style.maxHeight).toBe('400px');
});

test('mobile expansion reveals the selected preview without panning the desktop camera',()=>{
  const {app}=workbench({matchMedia:()=>({matches:true})});app.choose('s1');app.$nextTick=fn=>fn();
  const seen=[];app.$refs.world.querySelectorAll=()=>[{dataset:{objectId:'s1'},scrollIntoView:options=>seen.push(options)}];
  const pan={...app.pan};app.toggleComposer();expect(seen).toEqual([{block:'start',behavior:'instant'}]);expect(app.pan).toEqual(pan);
});

test('popup menus flip below high triggers and remain inside a narrow viewport',()=>{
  const {app}=workbench({innerWidth:360,innerHeight:500});
  const style=app.popupStyle({getBoundingClientRect:()=>({left:280,top:90,bottom:124})},320,400);
  expect(style.top).toBe('132px');expect(style.bottom).toBe('auto');
  expect(parseFloat(style.left)+parseFloat(style.width)).toBeLessThanOrEqual(344);
  expect(parseFloat(style.top)+parseFloat(style.maxHeight)).toBeLessThanOrEqual(484);
});

test('image budget above ten saves without resetting usage and blocks duplicate saves',async()=>{
  const {app}=workbench();app.cloudBudget={limit:10,reserved:10,remaining:0,max_calls:1000};app.cloudCalls=30;let resolve;const calls=[];
  app.projectApi=(path,body)=>{calls.push({path,body});return new Promise(done=>{resolve=done;});};
  const saving=app.saveCloudBudget();await app.saveCloudBudget();expect(calls).toEqual([{path:'/budget',body:{calls:30}}]);expect(app.cloudBudgetSaving).toBe(true);
  resolve({limit:30,reserved:10,remaining:20,max_calls:1000});await saving;expect(app.cloudBudget.reserved).toBe(10);expect(app.cloudBudgetMessage).toBe('已保存，可再生成 20 次');expect(app.cloudBudgetSaving).toBe(false);
});
test('invalid budget never sends a request and failed save preserves the requested limit',async()=>{
  const {app}=workbench();let calls=0;app.cloudBudget={limit:10,reserved:10,remaining:0,max_calls:1000};app.projectApi=async()=>{calls++;throw Error('连接失败，请重试');};
  for(const value of ['',null,-1,1.5,1001]){app.cloudCalls=value;await app.saveCloudBudget();expect(app.cloudBudgetError).toContain('整数');}
  expect(calls).toBe(0);app.cloudCalls=30;await app.saveCloudBudget();expect(app.cloudCalls).toBe(30);expect(app.cloudBudget.limit).toBe(10);expect(app.cloudBudgetError).toContain('连接失败');expect(app.cloudBudgetSaving).toBe(false);
});
test('stale backend capacity is shown honestly and cannot advertise support for a larger budget',async()=>{
  const {app}=workbench();app.cloudBudget={limit:10,reserved:10,remaining:0};app.cloudCalls=100;let calls=0;app.projectApi=async()=>{calls++;};
  expect(app.cloudBudgetHelp).toContain('后台仍限制 10 次');expect(app.cloudBudgetMaximum).toBe(10);await app.saveCloudBudget();expect(calls).toBe(0);expect(app.cloudBudgetError).toContain('重启');
  app.cloudBudget.max_calls=1000;expect(app.cloudBudgetMaximum).toBe(1000);expect(app.cloudBudgetHelp).toContain('支持 0–1000 次');
});

test('result selection resolves director to its shot, keeps the frame stable and uses image input',async()=>{
  const {app}=workbench();app.projectReady=true;app.videoJobs=[{id:'result',shot:'s1',media:'/result.mp4'}];app.flushProject=async()=>{};app.$nextTick=cb=>cb();app.$refs.director={contentWindow:{postMessage(){}}};
  app.choose('video-result');await app.openDirectorSelection('optimize');
  expect(app.directorContext.target).toBe('s1');expect(app.directorContext.node).toBe('video-result');expect(app.directorUrl).toContain('target=s1');expect(app.shotPreview(app.shots[0])).not.toBe('/result.mp4');
  const url=app.directorUrl;app.choose('macro');await app.openDirectorSelection();expect(app.directorUrl).toBe(url);expect(app.directorContext.target).toBe('macro');
});
test('switching image models submits the selected ID and keeps prior result provenance',async()=>{
  const {app}=workbench();const a=app.assets[0];app.choose(a.id);app.imagePanel=a.id;app.remember=()=>{};app.persist=()=>{};app.flushProject=async()=>{};
  app.modelCatalog=[['qwen-image-edit-plus','Qwen Image Edit Plus'],['qwen-image-2.0-pro','Qwen Image 2.0 Pro']].map(([model,label])=>({model,label,provider:'dashscope',tasks:['edit'],configured:true}));
  a.imageJob={task:'edit',state:'succeeded',provider:'dashscope',model:'qwen-image-edit-plus',output:'/old-plus.png',request_id:'old-plus'};
  app.setModel(app.modelCatalog[1]);expect(app.selectedModel().model).toBe('qwen-image-2.0-pro');expect(app.composerProgress()).toBe('上次结果 · Qwen Image Edit Plus');expect(app.composerImageJob.output).toBe('/old-plus.png');
  const calls=[];app.projectApi=async(path,body)=>{calls.push({path,body});return {task:body.task,state:'queued',model:body.model,provider:body.provider,request_id:body.request_id};};
  await app.submitComposer();expect(calls).toHaveLength(1);expect(calls[0].path).toBe('/images');expect(calls[0].body.model).toBe('qwen-image-2.0-pro');expect(calls[0].body.provider).toBe('dashscope');
  a.imageJob.state='succeeded';expect(app.composerProgress()).toBe('结果已生成 · Qwen Image 2.0 Pro');
});

test('inline prompt advice shares the sole frame with chat and closing only hides it',async()=>{
  const {app}=workbench();app.projectReady=true;app.flushProject=async()=>{};app.$nextTick=cb=>cb();
  app.$refs.director={contentWindow:{postMessage(){}}};app.$refs.promptAdvice={getBoundingClientRect:()=>({left:180,top:260,width:604,height:330})};
  app.choose('s1');await app.openDirectorSelection('optimize');
  expect(app.promptAdvice).toBe(true);expect(app.assistant).toBe(false);expect(app.composerExpanded).toBe(true);
  expect(app.promptAdviceStyle).toEqual({left:'180px',top:'260px',width:'604px',height:'330px'});
  const frame=app.directorUrl;app.closeDirector();expect(app.promptAdvice).toBe(false);expect(app.directorUrl).toBe(frame);
  await app.openDirectorSelection();expect(app.promptAdvice).toBe(false);expect(app.assistant).toBe(true);expect(app.directorUrl).toBe(frame);
  await app.openDirectorSelection('discuss','');expect(app.directorContext.target).toBe('');expect(app.directorContext.label).toBe('当前项目');expect(app.directorUrl).toBe(frame);
});

test('selecting another node hides advice without losing the shared connection or reusing its optimization intent',async()=>{
  const {app}=workbench();app.projectReady=true;app.flushProject=async()=>{};app.$nextTick=cb=>cb();app.$refs.director={contentWindow:{postMessage(){}}};
  app.choose('s1');await app.openDirectorSelection('optimize');const frame=app.directorUrl;
  const next=app.assets[0].id;app.choose(next);expect(app.promptAdvice).toBe(false);expect(app.assistant).toBe(false);expect(app.directorUrl).toBe(frame);
  await app.openDirectorSelection();expect(app.directorContext.target).toBe(next);expect(app.directorContext.intent).toBe('discuss');expect(app.assistant).toBe(true);
});

test('workspace menu failures preserve identity and expose retry instead of clearing the list',async()=>{
  const {app}=workbench({fetch:async()=>({ok:false})});app.projectName='产品短片';app.workspaceList=[{id:'fixture',name:'产品短片'}];await app.loadWorkspaceList();expect(app.workspaceListError).toContain('暂时');expect(app.projectName).toBe('产品短片');expect(app.workspaceList).toHaveLength(1);expect(app.workspaceListBusy).toBe(false);
});

test('image advice saves only text and rejects changed sources and unsaved prompts',async()=>{
  const {app}=workbench();app.projectReady=true;const replies=[];app.$refs.director={contentWindow:{postMessage:r=>replies.push(r)}};const asset=app.assets[0];app.directorConfirmed={target:asset.id};asset.imagePrompt='背景略暗';
  let saves=0;app.flushProject=async()=>{saves++;};app.remember=()=>{};app.persist=()=>{};
  const message={request:'image-advice',target:asset.id,before:'背景略暗',file:asset.file,task:'image-edit',prompt:'仅将背景略微压暗，包装文字保持'};
  const file=asset.file;await app.adoptDirectorImagePrompt(message);expect(asset.file).toBe(file);expect(asset.imagePrompt).toBe(message.prompt);expect(asset.imageEditPrompt).toBe(message.prompt);expect(saves).toBe(2);expect(replies.at(-1).ok).toBe(true);
  asset.imagePrompt='手动输入';await app.adoptDirectorImagePrompt(message);expect(asset.imagePrompt).toBe('手动输入');expect(saves).toBe(2);expect(replies.at(-1).error).toContain('已修改');
  asset.imagePrompt=message.before;asset.file='/new-source.png';await app.adoptDirectorImagePrompt(message);expect(saves).toBe(2);expect(replies.at(-1).error).toContain('图片已变化');
});

test('image advice failed save retains draft and can retry without a generation request',async()=>{
  const {app}=workbench();app.projectReady=true;const replies=[];app.$refs.director={contentWindow:{postMessage:r=>replies.push(r)}};const asset=app.assets[0];app.directorConfirmed={target:asset.id};asset.imagePrompt='原要求';app.remember=()=>{};app.persist=()=>{};
  let saves=0;app.flushProject=async()=>{if(++saves===2)throw Error('保存失败');};
  const message={request:'image-advice',target:asset.id,before:'原要求',file:asset.file,task:'image-edit',prompt:'优化建议'};
  await app.adoptDirectorImagePrompt(message);expect(replies.at(-1).ok).toBe(false);expect(asset.imagePrompt).toBe('优化建议');expect(app.directorAdopting).toBe(false);
  await app.adoptDirectorImagePrompt(message);expect(replies.at(-1).ok).toBe(true);expect(saves).toBe(4);
});
test('version category filters before pagination and lazy details recover complete text',async()=>{
  const {app}=workbench({document:{querySelector:()=>null}});app.$nextTick=cb=>cb();const paths=[];app.projectApi=async path=>{paths.push(path);return path.includes('/versions/')?{data:{text:'完整内容'.repeat(100)}}:{items:[{id:'v1',target:'narration',kind:'text'}],targets:[{id:'narration',kind:'text'}],page:1,total:1};};
  app.versionCategory='narration';await app.loadContentVersions();expect(paths[0]).toContain('category=narration');expect(app.categoryVersionTargets[0].id).toBe('narration');await app.loadVersionDetail({id:'v1',data:{text:'摘要'}},true);expect(app.versionDetails.v1.text.length).toBe(400);
});
test('corrupt backup does not conceal another valid backup',async()=>{
  const backup=JSON.stringify({workspace:'fixture',saved_at:123,state:{facts:'preserved'}});const {app}=workbench({localStorage:{getItem:()=>'{broken'},sessionStorage:{getItem:()=>backup}});expect(await app.readProjectBackup()).toBe(backup);
});
test('closing the director cancels a selection whose save is still in flight',async()=>{
  const {app}=workbench();let finish;app.flushProject=()=>new Promise(resolve=>{finish=resolve;});app.choose('s1');const opening=app.openDirectorSelection();app.closeDirector();finish();await opening;expect(app.assistant).toBe(false);expect(app.directorUrl).toBe('');
});
test('offscreen nodes cannot push the composer beyond a narrow viewport',()=>{
  const {app}=workbench();app.$refs.world.clientWidth=390;app.$refs.world.clientHeight=756;app.shots[0].x=1800;app.shots[0].y=900;app.choose('s1');const box=app.floatingStyle('composer');expect(parseFloat(box.left)+parseFloat(box.width)).toBeLessThanOrEqual(374);expect(parseFloat(box.left)).toBeGreaterThanOrEqual(16);
});
test('prompt adoption checks unsaved canvas edits, flushes first and locks editing until the command completes',async()=>{
  const {app}=workbench();app.projectReady=true;const replies=[];app.$refs.director={contentWindow:{postMessage:r=>replies.push(r)}};app.directorConfirmed={target:'s1'};const shot=app.shots.find(s=>s.id==='s1'),original=shot.prompt;app.flushProject=async()=>{};let writes=0,finish;
  app.projectApi=async(path,request)=>{writes++;expect(request.args.expected_prompt).toBe(original);const state=JSON.parse(JSON.stringify(app.projectSnapshot()));state.shots.find(s=>s.id==='s1').prompt='新提示词';return await new Promise(resolve=>{finish=()=>resolve({revision:2,state,events:[]});});};
  const message={request:'adopt-one',shot:'s1',before:original,owner:'owner',message:2};shot.prompt='尚未保存的手动改动';await app.adoptDirectorPrompt(message);expect(writes).toBe(0);expect(replies.at(-1).error).toContain('已修改');expect(shot.prompt).toBe('尚未保存的手动改动');
  shot.prompt=original;const adoption=app.adoptDirectorPrompt(message);await expect.poll(()=>writes).toBe(1);expect(app.directorAdopting).toBe(true);finish();await adoption;expect(app.directorAdopting).toBe(false);expect(app.shots.find(s=>s.id==='s1').prompt).toBe('新提示词');expect(replies.at(-1).ok).toBe(true);
});

test('narration delete, undo and saved state survive all production script layers',()=>{
  const {app,saved}=workbench();app.selection='narration';app.selectedIds=['narration'];app.voice=true;app.narrationNode.removed=false;
  app.removeNarration();expect(app.getTarget('narration')).toBeUndefined();expect(app.voice).toBe(false);
  expect(JSON.parse(saved.get('video-workspace-03')).narrationNode.removed).toBe(true);
  app.undo();expect(app.getTarget('narration')).toBeDefined();expect(app.voice).toBe(true);
  expect(JSON.parse(saved.get('video-workspace-03')).narrationNode.removed).toBe(false);
});
test('pan coalesces pointer input and commits the final pointer on release',()=>{
  const {app,frames,world,flush}=workbench();app.pan={x:10,y:20};app.drag={kind:'pan',x:100,y:100,ox:10,oy:20};
  app.dragMove({clientX:110,clientY:110});app.dragMove({clientX:140,clientY:150});
  expect(frames.size).toBe(1);expect(app.pan).toEqual({x:10,y:20});flush();
  expect(world.style.transform).toContain('translate(50px,70px)');
  app.dragMove({clientX:160,clientY:170});app.dragEnd();expect(app.pan).toEqual({x:70,y:90});expect(frames.size).toBe(0);
});
test('hand tool pans when started on a node while selection tool moves nodes',()=>{
  const {app}=workbench();const event={button:0,clientX:100,clientY:100,target:{closest:()=>null,setPointerCapture(){}},currentTarget:{setPointerCapture(){}},pointerId:1,preventDefault(){}};
  app.tool='hand';app.dragStart(event,'source');expect(app.drag.kind).toBe('pan');app.dragEnd();
  app.tool='select';app.dragStart(event,'source');expect(app.drag.kind).toBe('nodes');
  const x=app.assets[0].x;app.dragMove({...event,clientX:160});app.dragEnd();expect(app.assets[0].x).toBe(x+60);
});
test('organize has no narration or media overlap and remains undoable',()=>{
  const {app}=workbench();app.narrationNode.removed=false;const old=app.assets[0].x;app.organizeLayout();
  expect(app.narrationNode.x+app.narrationNode.w).toBeLessThan(app.assets[0].x);expect(app.assets[1].x+app.assets[1].w).toBeLessThan(app.shots[0].x);
  app.undo();expect(app.assets[0].x).toBe(old);
});

test('images inside buttons drag without native image drag while buttons remain clickable',()=>{
  const {app}=workbench();const image={closest:selector=>selector==='.asset-image,.plan-content'?{}:selector==='button,input,textarea,select,a'?{}:null};
  const e={button:0,clientX:100,clientY:100,target:image,currentTarget:{setPointerCapture(){}},preventDefault(){},pointerId:1};
  app.dragStart(e,'source');expect(app.drag.kind).toBe('nodes');const x=app.assets[0].x;app.dragMove({...e,clientX:180});app.dragEnd();expect(app.assets[0].x).toBe(x+80);
});
test('video result positions are independent objects and survive snapshot, refresh and undo',()=>{
  const {app}=workbench();app.videoJobs=[{id:'result-one',shot:'s1'}];const id='video-result-one';const original=app.videoPosition(app.videoJobs[0]).x;
  const e={button:0,clientX:100,clientY:100,target:{closest:()=>null},currentTarget:{setPointerCapture(){}},preventDefault(){},pointerId:1};
  app.dragStart(e,id);app.dragMove({...e,clientX:170});app.dragEnd();expect(app.videoPosition(app.videoJobs[0]).x).toBe(original+70);
  const restored=workbench().app;restored.videoJobs=app.videoJobs;Object.assign(restored,JSON.parse(JSON.stringify(app.projectSnapshot())));
  expect(restored.getTarget(id).x).toBe(original+70);app.undo();expect(app.videoPosition(app.videoJobs[0]).x).toBe(original);
});
test('ports bind actual frame/reference/brief relationships; disconnect and undo restore them',()=>{
  const {app}=workbench();app.shots[0].first='';expect(app.connectNodes('macro','s1')).toBe(true);expect(app.shots[0].first).toBe('macro');
  let edge=app.canvasEdges().find(e=>e.from==='macro');app.disconnectEdge(edge);expect(app.shots[0].first).toBe('');app.undo();expect(app.shots[0].first).toBe('macro');
  app.shots[0].mode='reference';app.shots[0].refs=[];app.connectNodes('source','s1');app.connectNodes('macro','s1');expect(app.shots[0].refs).toEqual(['source','macro']);expect(app.connectNodes('macro','s1')).toBe(false);
  app.notes=[{id:'brief',text:'创意',title:'方向',x:20,y:40,w:340,h:240}];expect(app.connectNodes('brief','s1')).toBe(true);expect(app.shots[0].creativeBrief).toBe('创意');
  expect(app.connectNodes('s1','source')).toBe(false);expect(app.canvasEdges().filter(e=>e.kind==='image')).toHaveLength(2);
});
test('image creation and editing keep actions in the composer and video actions in the composer while multiple selections retain their tools',()=>{
  const {app}=workbench();
  app.addImageGeneration();const draft=app.selection;
  expect(app.composerTask).toBe('generate');expect(app.showContextToolbar).toBe(false);
  app.removeNodes();expect(app.getTarget(draft)).toBeUndefined();app.undo();expect(app.getTarget(draft)).toBeDefined();
  app.choose('source');app.startImageEdit();expect(app.composerTask).toBe('edit');expect(app.showContextToolbar).toBe(false);
  app.choose('s1');expect(app.composerTask).toBe('video');expect(app.showContextToolbar).toBe(false);
  app.selectedIds=['source','macro'];app.selection='source';expect(app.showContextToolbar).toBe(true);
  app.backgroundClick();expect(app.showContextToolbar).toBe(false);
});

test('adding multiple references preserves the first frame, persists every edge and undo restores it',()=>{
  const {app}=workbench();const s=app.shots[0];s.first='source';s.mode='first';s.refs=[];
  app.assets.push({...app.assets[0],id:'third'});app.connectNodes('macro',s.id);app.connectNodes('third',s.id);
  expect(s.mode).toBe('reference');expect(s.refs).toEqual(['source','macro','third']);expect(app.canvasEdges().filter(e=>e.to===s.id&&e.kind==='image')).toHaveLength(3);
  const restored=workbench().app;Object.assign(restored,JSON.parse(JSON.stringify(app.projectSnapshot())));expect(restored.shots[0].refs).toEqual(['source','macro','third']);
  app.disconnectEdge(app.canvasEdges().find(e=>e.from==='macro'&&e.to===s.id));expect(app.shots[0].refs).toEqual(['source','third']);app.undo();expect(app.shots[0].refs).toEqual(['source','macro','third']);
  app.setInputMode('first');app.setInputMode('reference');expect(app.shots[0].refs).toEqual(['source','macro','third']);
});

test('multiple references are visible with an unsupported model and generation stays unavailable',()=>{
  const {app}=workbench();app.choose('s1');app.modelCatalog=[{provider:'minimax',model:'MiniMax-Hailuo-2.3',tasks:['video'],configured:true,references:false},{provider:'minimax',model:'MiniMax-H3',tasks:['video'],configured:true,references:true}];
  app.shots[0].videoProvider='minimax';app.shots[0].videoModel='MiniMax-Hailuo-2.3';app.shots[0].mode='reference';app.shots[0].refs=['source','macro'];
  expect(app.composerRefs()).toHaveLength(2);expect(app.referenceWarning).toContain('MiniMax H3');app.setModel(app.modelCatalog[1]);expect(app.referenceWarning).toBe('');
});

test('a hashed asset filename is replaced by the readable project idea',()=>{
  const {context}=workbench();expect(context.shortStudioName('0c90b48dc2e531020c520c008b6dd5d3.jpg',[{title:'BUV 小绿泥 · 创作方案'}])).toBe('BUV 小绿泥');expect(context.shortStudioName('a'.repeat(32)+'.png')).toBe('未命名画布');
});
test('a fresh canvas has no automatic narration, and adding/removing it is undoable',()=>{
  const {app}=workbench();app.$refs.world.querySelectorAll=()=>[];expect(app.getTarget('narration')).toBeUndefined();app.addNarration();expect(app.getTarget('narration')).toBeDefined();expect(app.narration).toBe('');app.removeNarration();expect(app.getTarget('narration')).toBeUndefined();app.undo();expect(app.getTarget('narration')).toBeDefined();
});

test('video picture drag moves the real node while native playback controls keep their pointer input',()=>{
  const {app}=workbench();app.videoJobs=[{id:'playable',shot:'s1',media:'/real.mp4'}];const video={getBoundingClientRect:()=>({bottom:400})};
  const event={button:0,clientX:100,clientY:200,target:{closest:q=>q==='video'?video:null},currentTarget:{setPointerCapture(){}},preventDefault(){},pointerId:1};
  app.dragStart({...event,clientY:390},'video-playable');expect(app.drag).toBeFalsy();
  app.dragStart(event,'video-playable');expect(app.drag.kind).toBe('nodes');const x=app.getTarget('video-playable').x;
  app.dragMove({...event,clientX:160});app.dragEnd();expect(app.getTarget('video-playable').x).toBe(x+60);
});

test('result connections are smooth, unlabeled and terminate at the input port',()=>{
  const {app}=workbench();app.assets=[];app.notes=[];app.narrationNode.removed=true;
  app.shots=[{id:'one',x:1080,y:40},{id:'two',x:1540,y:40}];app.videoJobs=[{id:'moved',shot:'one'}];app.canvasLayout={'video-moved':{x:1325,y:415}};
  const route=app.edgeGeometry({kind:'result',from:'one',to:'video-moved'});
  expect(route.path).toContain(' C ');expect(route.path).not.toContain(' L ');expect(route.path.endsWith('1325 660.5')).toBe(true);expect(route.label).toBeUndefined();
});

test('deleting an image and video together restores both with one undo',()=>{
  const {app}=workbench();app.videoJobs=[{id:'mixed',shot:'s1'}];app.videoPosition(app.videoJobs[0]);
  app.removeNodes(['source','video-mixed']);expect(app.assets.some(a=>a.id==='source')).toBe(false);expect(app.getTarget('video-mixed')).toBeUndefined();
  app.undo();expect(app.assets.some(a=>a.id==='source')).toBe(true);expect(app.getTarget('video-mixed')).toBeDefined();expect(app.history).toHaveLength(0);
});

test('task model choices persist independently on each media node and undo restores the choice',()=>{
  const {app}=workbench();app.modelCatalog=[{provider:'minimax',model:'MiniMax-H3',label:'H3',configured:true,tasks:['video']},{provider:'dashscope',model:'wan2.2-i2v-flash',configured:true,tasks:['video']},{provider:'dashscope',model:'qwen-image-edit-plus',configured:true,tasks:['edit']},{provider:'minimax',model:'image-01',configured:true,tasks:['generate']}];
  app.shots.push({...app.shots[0],id:'second-shot'});const first=app.shots[0],second=app.shots[1];app.choose(first.id);app.setModel(app.modelCatalog[0]);
  app.choose(second.id);app.setModel(app.modelCatalog[1]);expect(first.videoModel).toBe('MiniMax-H3');expect(second.videoProvider).toBe('dashscope');
  const restored=workbench().app;Object.assign(restored,JSON.parse(JSON.stringify(app.projectSnapshot())));restored.modelCatalog=app.modelCatalog;restored.choose(first.id);
  expect(restored.selectedModel().model).toBe('MiniMax-H3');app.undo();expect(app.shots[1].videoModel).toBeUndefined();
  app.choose('source');app.startImageEdit();expect(app.modelsFor(app.composerTask).map(m=>m.model)).toEqual(['qwen-image-edit-plus']);
  app.setModel(app.modelCatalog[2]);expect(app.assets[0].imageModel).toBe('qwen-image-edit-plus');expect(app.shots[0].videoModel).toBe('MiniMax-H3');
});

test('image composer submits the selected task and model and records the original receipt',async()=>{
  const {app}=workbench();const a=app.assets[0];app.choose(a.id);app.startImageEdit();a.imagePrompt='保留产品，调整背景';
  app.modelCatalog=[{provider:'dashscope',model:'qwen-image-edit-plus',configured:true,tasks:['edit']}];app.projectRevision=8;app.flushProject=async()=>{};
  let submitted;app.projectApi=async(path,body)=>{submitted={path,body};return {project:'precision-fixture',job:'original-job',request_id:body.request_id,state:'queued'}};
  await app.submitComposer();expect(submitted.path).toBe('/images');expect(submitted.body).toMatchObject({model:'qwen-image-edit-plus',provider:'dashscope',task:'edit',object:a.id,revision:8});
  expect(a.imageJob.job).toBe('original-job');expect(app.composerBusy()).toBe(true);
});

test('video composer pins the node model before invoking the durable video submission',async()=>{
  const {app}=workbench();app.shots.push({...app.shots[0],id:'second-shot'});app.choose(app.shots[1].id);app.modelCatalog=[{provider:'minimax',model:'MiniMax-H3',configured:true,tasks:['video']}];
  let chosen;app.generateVideo=async()=>{chosen={active:app.active,model:app.shot.videoModel,provider:app.shot.videoProvider}};
  await app.submitComposer();expect(chosen).toEqual({active:app.shots[1].id,model:'MiniMax-H3',provider:'minimax'});
});

test('floating controls use measured dimensions and leave room for the canvas dock',()=>{
  const {app}=workbench();app.$refs.world.clientWidth=1280;app.$refs.world.clientHeight=572;app.pan={x:0,y:0};app.zoom=1;
  app.shots[0].x=450;app.shots[0].y=320;app.choose(app.shots[0].id);app.toolbarWidth=60;app.composerHeight=318;
  expect(app.floatingStyle('toolbar')).toMatchObject({left:'539px'});expect(Number.parseFloat(app.floatingStyle('composer').top)+app.composerHeight).toBeLessThanOrEqual(app.$refs.world.clientHeight-68);
  app.toolbarWidth=380;expect(app.floatingStyle('toolbar')).toMatchObject({left:'379px'});
  app.shots[0].x=1100;const positioned=app.floatingStyle('composer');expect(Number.parseFloat(positioned.left)+Number.parseFloat(positioned.width)).toBeLessThan(app.shots[0].x);
});

test('reference curves use one smooth segment regardless of unrelated overlapping media',()=>{
  const {app,context}=workbench();app.assets=[{id:'source',x:0,y:100,w:100,h:100},{id:'obstacle',x:240,y:90,w:150,h:130}];app.notes=[];app.narrationNode.removed=true;app.videoJobs=[];app.shots=[{id:'destination',x:600,y:0}];
  const path=app.edgeGeometry({from:'source',to:'destination'}).path;
  const coordinates=path.match(/-?\d+(?:\.\d+)?/g).map(Number),start={x:coordinates[0],y:coordinates[1]},segments=[start];
  for(let i=2;i<coordinates.length;i+=6)segments.push([{x:coordinates[i],y:coordinates[i+1]},{x:coordinates[i+2],y:coordinates[i+3]},{x:coordinates[i+4],y:coordinates[i+5]}]);
  expect(segments).toHaveLength(2);expect(path.endsWith('600 245.5')).toBe(true);
  app.assets[1].x=800;app.assets[1].y=800;expect(app.edgeGeometry({from:'source',to:'destination'}).path).toBe(path);
});

test('organize measures tall media, stacks results separately and clears floating controls',()=>{
  const {app}=workbench();app.notes=[{id:'wide-note',x:60,y:40,w:640,h:300}];app.assets[0].h=900;app.assets[1].h=700;app.videoJobs=[{id:'one',shot:app.shots[0].id},{id:'two',shot:app.shots[0].id}];app.choose(app.assets[0].id);app.startImageEdit();
  app.organizeLayout();expect(app.selection).toBe('');expect(app.imagePanel).toBe('');expect(app.zoom).toBeGreaterThanOrEqual(.55);
  const nodes=app.objects();for(let i=0;i<nodes.length;i++)for(let j=i+1;j<nodes.length;j++){const a=nodes[i],b=nodes[j];expect(a.x+a.w<=b.x||b.x+b.w<=a.x||a.y+a.h<=b.y||b.y+b.h<=a.y).toBe(true);}
  app.undo();expect(app.assets[0].h).toBe(900);
});

test('selection, floating panels, pan and zoom never reroute an unchanged connection',()=>{
  const {app}=workbench();app.assets=[{id:'source',x:0,y:450,w:100,h:100}];app.notes=[];app.narrationNode.removed=true;app.videoJobs=[];app.shots=[{id:'destination',x:600,y:100}];
  const edge={from:'source',to:'destination'},before=app.edgeGeometry(edge);
  app.choose('destination');app.zoom=.55;app.pan={x:80,y:20};app.composerHeight=350;app.floatingStyle=()=>({left:'140px',top:'350px',width:'300px'});
  expect(app.edgeGeometry(edge)).toBe(before);
  app.composerHeight=520;app.clearCanvasSelection();expect(app.edgeGeometry(edge)).toBe(before);
});

test('connected node drag previews only related edges and commits once on release',()=>{
  const {app,flush}=workbench();const node={dataset:{objectId:'source'},style:{removeProperty:viRemove}},paths=[{setAttribute:()=>calls++}];let calls=0;
  function viRemove(key){delete this[key];}
  const unrelated={dataset:{edgeId:'unrelated'},querySelectorAll:()=>[{setAttribute:()=>{throw Error('unrelated edge repainted')}}]};
  app.$refs.world.querySelectorAll=selector=>selector==='[data-object-id]'?[node]:[{dataset:{edgeId:'source>s1'},querySelectorAll:()=>paths},unrelated];
  app.shots[0].first='source';const oldX=app.getTarget('source').x;const event={button:0,clientX:100,clientY:100,target:{closest:()=>null},currentTarget:{setPointerCapture(){}},pointerId:1,preventDefault(){}};
  app.dragStart(event,'source');app.dragMove({...event,clientX:120});app.dragMove({...event,clientX:150});flush();
  expect(app.getTarget('source').x).toBe(oldX);expect(node.style.transform).toBe('translate(50px,0px)');expect(calls).toBe(1);
  app.dragMove({...event,clientX:180});app.dragEnd();expect(app.getTarget('source').x).toBe(oldX+80);expect(node.style.transform).toBeUndefined();
  app.undo();expect(app.getTarget('source').x).toBe(oldX);
});

test('repair result opens comparison with its durable candidate job after generation adoption',async()=>{
  const {app}=workbench();const a=app.assets[0];app.choose(a.id);app.startImageEdit();app.projectRevision=12;
  a.imageJob={task:'edit',project:'real-project',job:'real-job',output:'/candidate.png',state:'succeeded'};
  let compared=false;app.refreshEditorComparison=async()=>{expect(app.editorCandidate.job.id).toBe('real-job');compared=true;};
  await app.adoptComposerImage();expect(compared).toBe(true);expect(app.fullEditor).toBe(true);expect(app.editorCandidate.job.id).toBe('real-job');expect(app.compareBasis).toBe(12);
  expect(a.file).not.toBe('/candidate.png');
});


test('blank canvas click clears every floating context while preserving image edit draft',()=>{
  const {app}=workbench();app.choose('source');app.startImageEdit();app.composerAsset.imagePrompt='保留草稿';app.composerAsset.imageEditPrompt='保留草稿';
  app.modelMenu=true;app.referenceMenu=true;app.selectedEdge={id:'old'};
  app.backgroundClick();expect(app.selection).toBe('');expect(app.selectedIds).toEqual([]);expect(app.composerTask).toBe('');expect(app.hasCanvasSelection).toBe(false);
  expect(app.imagePanel).toBe('');expect(app.modelMenu).toBe(false);expect(app.referenceMenu).toBe(false);expect(app.selectedEdge).toBeNull();expect(app.floatingStyle('toolbar')).toEqual({});
  app.choose('source');app.startImageEdit();expect(app.composerAsset.imagePrompt).toBe('保留草稿');expect(app.composerTask).toBe('edit');
});

test('stale selection cannot expose delete toolbar or an empty edit composer',()=>{
  const {app}=workbench();app.choose('source');app.startImageEdit();app.selectedIds=[];
  expect(app.hasCanvasSelection).toBe(false);expect(app.composerTask).toBe('');expect(app.floatingStyle('toolbar')).toEqual({});
  app.selection='';app.imagePanel='';expect(app.composerTask).toBe('');
  app.selection='missing';app.selectedIds=['missing'];expect(app.hasCanvasSelection).toBe(false);
});

test('marquee and panning gestures do not become blank canvas clicks',()=>{
  const {app}=workbench();app.pan={x:0,y:0};app.zoom=1;app.choose('source');app.startImageEdit();
  app.drag={kind:'pan',ox:0,oy:0,x:10,y:10};app.dragMove({clientX:40,clientY:10});app.dragEnd();app.backgroundClick();expect(app.selection).toBe('source');
  app.dragClick=false;const n=app.assets[0];app.drag={kind:'marquee',start:{x:n.x-2,y:n.y-2}};app.marquee={x:n.x-2,y:n.y-2,w:n.w+4,h:n.h+4};
  app.dragEnd();app.backgroundClick();expect(app.selectedIds).toContain('source');expect(app.selection).toBe(app.selectedIds[0]);
  app.dragClick=false;app.drag={kind:'marquee',start:{x:n.x+20,y:n.y+20}};app.marquee={x:n.x+20,y:n.y+20,w:0,h:0};app.dragEnd();
  expect(app.selection).toBe('');expect(app.composerTask).toBe('');
});

test('Chat waits for durable save, exposes failures, and retry navigates using the original destination',async()=>{
  const {app,context}=workbench();app.projectReady=true;const destination='/?workspace=fixture&target=s1';
  let release;app.flushProject=()=>new Promise(resolve=>{release=resolve});const click={preventDefault(){},currentTarget:{href:destination}};
  const opening=app.openFullChat(click);expect(app.chatOpening).toBe(true);expect(context.location.href).toBeUndefined();click.currentTarget=null;release();await opening;
  expect(context.location.href).toBe(destination);
  context.location.href=undefined;app.flushProject=async()=>{throw Error('连接中断')};await app.openFullChat({...click,currentTarget:{href:destination}});
  expect(context.location.href).toBeUndefined();expect(app.projectError).toContain('打开完整对话前保存未完成');expect(app.pendingChatHref).toBe(destination);
  app.flushProject=async()=>{};await app.retryProjectSave();expect(context.location.href).toBe(destination);
});

test('expired session refresh retries the exact save receipt only after auth rejection',async()=>{
  const calls=[];const {app,context}=workbench({AbortSignal,WORKSPACE_TOKEN:'old-token',fetch:async(url,options)=>{
    calls.push({url,options});if(url==='/studio/index.html')return {ok:true,text:async()=>'<script>window.WORKSPACE_TOKEN="new-token";</script>'};
    if(options.headers['X-Hermes-Session-Token']==='old-token')return {ok:false,status:401};
    return {ok:true,status:200,json:async()=>({revision:8})};
  }});
  const body={request_id:'same-receipt',revision:7,state:{facts:'原稿'}};expect(await app.projectApi('',body)).toMatchObject({revision:8});
  expect(calls).toHaveLength(3);expect(calls[0].options.body).toBe(calls[2].options.body);expect(context.WORKSPACE_TOKEN).toBe('new-token');
  calls.length=0;context.fetch=async(url,options)=>{calls.push({url,options});return {ok:false,status:409,json:async()=>({detail:'版本冲突'})}};
  await expect(app.projectApi('',body)).rejects.toMatchObject({status:409});expect(calls).toHaveLength(1);
});


test('conflict recovery backs up the current draft before clearing receipts even when local storage is full',async()=>{
  const session=new Map();const {app,context}=workbench({Blob,URL:{createObjectURL:()=>'/backup',revokeObjectURL(){}},document:{createElement:()=>({click(){}})},sessionStorage:{getItem:k=>session.get(k)||null,setItem:(k,v)=>session.set(k,v),removeItem:k=>session.delete(k)}});
  app.projectError='版本冲突';app._pendingRequest={request_id:'original-receipt'};app.assets[0].imagePrompt='未保存的编辑';app.pendingChatHref='/?workspace=fixture';
  context.localStorage.setItem=()=>{throw Error('quota')};app.projectApi=async()=>({state:{},revision:9});
  let navigated=false;app.loadSharedProject=async()=>{expect(JSON.parse(session.get('video-workspace-backup:fixture')).state.assets[0].imagePrompt).toBe('未保存的编辑');app.projectError='';};app.continueToChat=async()=>{navigated=true};
  await app.preserveAndReadLatest();expect(app._pendingRequest).toBeNull();expect(navigated).toBe(true);
});


test('continue from a cloud candidate applies it to the working document before reopening, without project adoption',async()=>{
  const {app}=workbench();app.editorCandidate={revision:4,job:{id:'result-job'}};app.editorProject='image-project';app.editAssetId='source';app.editSource={file:'source.png'};app.adoptShot='s1';app.editorUrl='';
  const calls=[];app.editApi=async(path,body)=>{calls.push({path,body});return {revision:5}};app.closeFullEditor=()=>calls.push({close:true});app.openDirectorPrecision=async target=>calls.push({open:target});
  await app.continueFullPrecision();expect(calls[0]).toEqual({path:'/full/image-project/apply-preview',body:{revision:4,kind:'job',id:'result-job'}});
  expect(calls.at(-1).open.source).toBe('source.png');expect(app.editorApplying).toBe(false);expect(calls).toHaveLength(3);
});

test('continuing preserves the comparison if applying the selected version fails',async()=>{
  const {app}=workbench();const candidate={revision:4,job:{id:'result-job'}};app.editorCandidate=candidate;app.editorProject='image-project';app.editApi=async()=>{throw Error('版本已改变')};let reopened=false;app.openDirectorPrecision=async()=>{reopened=true};
  await app.continueFullPrecision();expect(reopened).toBe(false);expect(app.editorCandidate).toBe(candidate);expect(app.editorFailure).toBe('版本已改变');
});


test('retained candidate recovery refreshes the comparison without applying or regenerating it',async()=>{
  const {app}=workbench({URL:{revokeObjectURL(){}},fetch:async()=>({ok:true,json:async()=>({revision:14})})});
  Object.assign(app,{editorCandidate:{revision:2,job:{id:'retained-job'}},editorProject:'image-project',editAssetId:'source',editSource:{file:'source.png'},editorFailure:'工作图已变化',previewUrls:[],flushProject:async()=>{},projectApi:async()=>({revision:20,state:{assets:[{id:'source',file:'source.png'}]}}),notify:()=>{}});
  const calls=[];app.editApi=async(path,body)=>{calls.push({path,body});return {revision:14,comparison:{id:'snapshot',job:'retained-job'},output:'/after.png',before_output:'/before.png'}};
  await app.refreshEditorComparison();expect(calls).toEqual([{path:'/full/image-project/compare-job',body:{revision:14,job:'retained-job'}}]);
  expect(app.editorCandidate.comparison.id).toBe('snapshot');expect(app.previewBefore).toBe('/before.png');expect(app.compareBasis).toBe(20);expect(app.editorFailure).toBe('');
});

test('comparison recovery preserves the selected result when the original asset changed',async()=>{
  const {app}=workbench();const candidate={revision:2,job:{id:'retained-job'}};app.editorCandidate=candidate;app.editAssetId='source';app.editSource={file:'source.png'};app.flushProject=async()=>{};
  app.projectApi=async()=>({revision:20,state:{assets:[{id:'source',file:'new.png'}]}});let writes=0;app.editApi=async()=>{writes++};
  await app.refreshEditorComparison();expect(writes).toBe(0);expect(app.editorCandidate).toBe(candidate);expect(app.editorFailure).toContain('原图已改变');expect(app.editorApplying).toBe(false);
});

test('reviewed snapshot is applied before project adoption and retries retain the same request',async()=>{
  const {app,saved}=workbench();app.editorCandidate={revision:14,comparison:{id:'reviewed-snapshot',job:'retained-job'}};app.editorProject='image-project';app.editAssetId='source';app.editSource={file:'source.png'};app.compareBasis=20;app.flushProject=async()=>{};
  const calls=[];app.editApi=async(path,body)=>{calls.push({path,body});return path.endsWith('/preview')?{revision:15,output_id:'exported',output:'/export.png'}:{revision:15};};
  let fail=true;app.projectApi=async(path,body)=>{calls.push({path,body});if(fail)throw Error('连接中断');return {revision:21,state:app.projectSnapshot(),events:[]};};app.closeFullEditor=()=>{};app.persist=()=>{};app.notify=()=>{};app.syncDirectorTarget=()=>{};
  await app.adoptFullEditor();expect(calls[0]).toEqual({path:'/full/image-project/apply-preview',body:{revision:14,kind:'comparison',id:'reviewed-snapshot'}});
  const request=JSON.parse(saved.get('studio-adopt:fixture'));expect(request.args.revision).toBe(15);fail=false;await app.adoptFullEditor();expect(calls.filter(c=>c.path.endsWith('/apply-preview'))).toHaveLength(1);expect(calls.at(-1).body).toEqual(request);expect(saved.has('studio-adopt:fixture')).toBe(false);
});


test('image adoption refreshes expired authentication without changing the preview receipt',async()=>{
  const calls=[];const {app,context}=workbench({WORKSPACE_TOKEN:'old-token',fetch:async(url,options)=>{
    calls.push({url,options});if(url==='/studio/index.html')return {ok:true,text:async()=>'<script>window.WORKSPACE_TOKEN="new-token";</script>'};
    if(options.headers['X-Hermes-Session-Token']==='old-token')return {ok:false,status:401};
    return {ok:true,status:200,json:async()=>({revision:15})};
  }});
  const body={revision:14,kind:'comparison',id:'reviewed-snapshot'};expect(await app.editApi('/full/project/apply-preview',body)).toMatchObject({revision:15});
  expect(calls).toHaveLength(3);expect(calls[0].options.body).toBe(calls[2].options.body);expect(context.WORKSPACE_TOKEN).toBe('new-token');
});


test('composer feedback distinguishes submission from a running task without changing its inputs',()=>{
  const {app}=workbench();app.choose(app.assets[0].id);app.startImageEdit();const a=app.composerAsset;a.imagePrompt='保留原文字';a.imageJob={task:'edit',state:'running'};
  expect(app.composerBusy()).toBe(true);expect(app.composerProgress()).toBe('正在修图');app.imageBusy=true;expect(app.composerProgress()).toBe('正在提交…');
  app.imageBusy=false;a.imageJob.state='queued';expect(app.composerProgress()).toBe('任务排队中');a.imageJob.state='succeeded';expect(app.composerBusy()).toBe(false);expect(app.composerProgress()).toBe('结果已生成');expect(a.imagePrompt).toBe('保留原文字');
});

test('older backend 405 uses guarded previews without changing the work or regenerating',async()=>{
  let urlId=0;const {app}=workbench({URL:{createObjectURL:()=>'/blob-'+(++urlId),revokeObjectURL(){}}});
  const document={layers:[{id:'layer',kind:'image',asset_id:'current-local',visible:true,locked:false}]};
  const selected={revision:2,job:{id:'retained-job'}};Object.assign(app,{editorCandidate:selected,editorProject:'project',editAssetId:'source',editSource:{file:'source.png'},previewUrls:[],flushProject:async()=>{},projectApi:async()=>({revision:20,state:{assets:[{id:'source',file:'source.png'}]}}),notify:()=>{}});
  app.editApi=async()=>{const error=new Error('Method Not Allowed');error.status=405;throw error;};const calls=[];
  app.workingApi=async(path,body,method,binary)=>{calls.push({path,body,method,binary});if(path.endsWith('/jobs/retained-job'))return {state:'succeeded',layer_id:'layer',output:{id:'new-result'}};if(binary)return new Blob(['pixels']);return {revision:14,document};};
  await app.refreshEditorComparison();expect(app.editorFailure).toBe('');expect(app.editorCandidate.legacyComparison.document.layers[0].asset_id).toBe('new-result');expect(document.layers[0].asset_id).toBe('current-local');expect(app.previewBefore).toBe('/blob-1');expect(app.editorCandidate.output).toBe('/blob-2');
  expect(calls.filter(c=>c.body)).toHaveLength(2);expect(calls.every(c=>!c.path.endsWith('/document'))).toBe(true);
});

test('legacy comparison saves only its reviewed version and recognizes a completed retry',async()=>{
  const {app}=workbench();app.editorProject='project';const document={layers:[{id:'layer',asset_id:'new-result'}]};const candidate={revision:14,legacyComparison:{document,job:'retained-job',output:'new-result'}};
  let revision=14,savedDoc={layers:[{id:'layer',asset_id:'old-result'}]},writes=0;
  app.workingApi=async(path,body,method)=>{if(path.includes('/jobs/'))return {state:'succeeded',output:{id:'new-result'}};if(body){expect(method).toBe('PUT');expect(body.revision).toBe(14);writes++;revision++;savedDoc=body.document;return {revision,document:savedDoc};}return {revision,document:savedDoc};};
  expect((await app.applyEditorPreview(candidate)).revision).toBe(15);expect((await app.applyEditorPreview(candidate)).revision).toBe(15);expect(writes).toBe(1);
  savedDoc={layers:[{id:'layer',asset_id:'different-edit'}]};await expect(app.applyEditorPreview(candidate)).rejects.toMatchObject({status:409});expect(writes).toBe(1);
  revision=16;await expect(app.applyEditorPreview(candidate)).rejects.toMatchObject({status:409});expect(writes).toBe(1);
});

test('comparison API conflicts do not activate legacy saving and retain the previous candidate',async()=>{
  const {app}=workbench();const selected={revision:2,job:{id:'retained-job'}};Object.assign(app,{editorCandidate:selected,editorProject:'project',editAssetId:'source',editSource:{file:'source.png'},flushProject:async()=>{},projectApi:async()=>({revision:20,state:{assets:[{id:'source',file:'source.png'}]}})});
  app.workingApi=async()=>({revision:14});app.editApi=async()=>{const error=new Error('比较期间又有修改');error.status=409;throw error;};app.legacyJobComparison=async()=>{throw Error('must not bypass conflict')};
  await app.refreshEditorComparison();expect(app.editorCandidate).toBe(selected);expect(app.editorFailure).toBe('比较期间又有修改');
});
