import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {expect,test,vi} from 'vitest';

function studio(){
  const context={crypto:{randomUUID:()=> 'fixture-id'},URLSearchParams,AbortSignal,
    location:{search:'?workspace=fixture',origin:'http://localhost'},
    localStorage:{getItem:()=>null,setItem(){},removeItem(){}},sessionStorage:{getItem:()=>null,setItem(){},removeItem(){}},
    setTimeout:()=>1,clearTimeout(){},setInterval(){},clearInterval(){},matchMedia:()=>({matches:false})};
  context.window=context;
  for(const name of ['project-name','usability','workflow','app','integration','production','node-composer','interaction'])
    runInNewContext(readFileSync(new URL('../public/studio/'+name+'.js',import.meta.url),'utf8'),context);
  const app=context.film();app.$refs={world:{clientWidth:1000,clientHeight:800}};app.$nextTick=fn=>fn();
  return app;
}

test('selecting a node preserves the canvas camera and keeps the assistant closed',()=>{
  const app=studio();const pan={...app.pan};
  app.choose('s1');expect(app.assistant).toBe(false);expect(app.inspectorKind).toBe('视频镜头');
  expect(app.pan).toEqual(pan);
  app.toggleComposer();expect(app.composerExpanded).toBe(true);
  expect(app.floatingStyle('composer').width).toBe('640px');
  expect(app.shots[0].first).toBe('source');
});
test('the canvas editor fits a narrow canvas without overriding visibility or changing node data',()=>{
  const app=studio();app.choose('s1');app.composerExpanded=true;
  app.$refs.world.clientWidth=500;app.pan={x:1000,y:600};
  const position=app.floatingStyle('composer');
  expect(position.width).toBe('468px');expect(position.left).toBe('16px');
  expect(position.display).toBeUndefined();expect(parseFloat(position.top)).toBeGreaterThanOrEqual(12);
  expect(parseFloat(position.top)+app.composerHeight).toBeLessThanOrEqual(800-84);
  app.selectionMore=true;app.clearCanvasSelection();expect(app.selectionMore).toBe(false);
  expect(app.shots[0].first).toBe('source');
});
test('inspector uses readable asset names while preserving the original filename',()=>{
  const app=studio();app.assets[0].name='a'.repeat(32)+'.png';app.choose('source');
  expect(app.inspectorTitle).toBe('图片 1');expect(app.assets[0].name).toBe('a'.repeat(32)+'.png');
  app.clearCanvasSelection();expect(app.inspectorTitle).toBe('未选择节点');
});

test('explicit image lookup keeps the image beside an expanded editor when both fit',()=>{
  const app=studio();app.assets[0].w=200;app.assets[0].h=400;
  app.choose('source');app.imagePanel='source';app.composerExpanded=true;app.composerHeight=380;app.zoom=1;
  const anchor=app.panelAnchor();app.pan={x:500-anchor.x,y:150-anchor.y};
  const originalY=app.pan.y;app.revealComposerTarget();
  const editor=app.floatingStyle('composer');const left=app.pan.x+anchor.x;
  expect(parseFloat(editor.left)>=left+anchor.w||parseFloat(editor.left)+parseFloat(editor.width)<=left).toBe(true);
  expect(app.pan.y).toBe(originalY);
  app.pan={x:500-anchor.x,y:500-anchor.y};app.revealComposerTarget();
  expect(app.pan.y+anchor.y+anchor.h).toBeLessThanOrEqual(app.$refs.world.clientHeight-84);
});
test('an explicitly selected timeline clip previews its actual media when a render exists',()=>{
  const app=studio();app.videoJobs=[{id:'take',shot:'s1',state:'succeeded',media:'/take.mp4'}];
  app.sequence=[{job:'take'}];app.videoRenders=[{state:'succeeded',media:'/whole.mp4'}];
  app.assemblyClip='take';expect(app.assemblyPreview).toBe('/take.mp4');
  app.assemblyClip='';expect(app.assemblyPreview).toBe('/whole.mp4');
});

test('empty shot selection opens its image picker with Chat materials without changing the plan',async()=>{
  const app=studio();app.shots[0].first='';app.revealComposerTarget=vi.fn();
  app.projectApi=vi.fn(async()=>[{id:'chat-photo',name:'产品.png',file:'/photo.png'}]);
  const prompt=app.shots[0].prompt;
  await app.openShotImagePicker('s1');await Promise.resolve();
  expect(app.referenceMenu).toBe(true);expect(app.composerExpanded).toBe(true);
  expect(app.availableChatMaterials.map(x=>x.id)).toEqual(['chat-photo']);
  expect(app.projectApi).toHaveBeenCalledWith('/assets/chat');
  expect(app.shots[0].first).toBe('');expect(app.shots[0].prompt).toBe(prompt);
});

test('choosing another first frame replaces the frame without changing to multiple references',()=>{
  const app=studio();app.assets.push({id:'other',name:'另一张',file:'/other.png'});app.choose('s1');
  app.addReference('other');
  expect(app.shots[0].first).toBe('other');expect(app.shots[0].mode).toBe('first');
  expect(app.shots[0].inputReview).toBe(false);expect(app.referenceMenu).toBe(false);
  expect(app.canvasEdges().some(e=>e.from==='other'&&e.to==='s1')).toBe(true);
});

test('importing a Chat material selects its actual saved canvas node and persists the frame',async()=>{
  const app=studio();app.choose('s1');app.flushProject=vi.fn(async()=>{});
  app.projectApi=vi.fn(async()=>({object:'imported-photo',revision:2}));
  app.refreshProjectChanges=vi.fn(async()=>app.assets.push({id:'imported-photo',name:'产品.png',file:'/photo.png',source:{attachmentId:'chat-photo'}}));
  await app.useChatMaterial({id:'chat-photo',name:'产品.png',file:'/photo.png'});
  expect(app.shots[0].first).toBe('imported-photo');expect(app.shots[0].mode).toBe('first');
  expect(app.projectApi).toHaveBeenCalledWith('/assets/import-chat',{request_id:'fixture-id',attachment:'chat-photo'});
  expect(app.flushProject).toHaveBeenCalledTimes(2);expect(app.referenceBusy).toBe(false);
});

test('an unsynchronised local draft is preserved when imported material cannot yet be applied',async()=>{
  const app=studio();app.choose('s1');const before=JSON.stringify(app.shots);
  app.flushProject=vi.fn(async()=>{});app.projectApi=vi.fn(async()=>({object:'imported-photo'}));
  app.refreshProjectChanges=vi.fn(async()=>{});
  await app.useChatMaterial({id:'chat-photo'});
  expect(JSON.stringify(app.shots)).toBe(before);expect(app.composerError).toContain('当前编辑仍保留');
  expect(app.referenceBusy).toBe(false);
});

test('returning from prompt refill opens the canvas image editor with its selected model',()=>{
  const listeners={},frame={};
  const asset={id:'photo',imageModel:'chosen-model',imagePrompt:'确认后的要求'};
  const base={init(){},$watch:vi.fn(),choose:vi.fn(),assets:[asset],$refs:{director:{contentWindow:frame}},workspaceId:'fixture',closeDirector:vi.fn(),revealComposerTarget:vi.fn(),$nextTick:fn=>fn()};
  const context={base,location:{origin:'http://localhost'},setTimeout:fn=>fn(),window:{innerWidth:1280,addEventListener:(type,fn)=>listeners[type]=fn}};
  const app=runInNewContext(readFileSync(new URL('../public/studio/interaction.js',import.meta.url),'utf8')+';withStudioInteraction(base)',context);
  app.closeDirector=vi.fn();app.choose=vi.fn(id=>app.selection=id);app.revealComposerTarget=vi.fn();
  app.init();const event={origin:'http://localhost',source:frame,data:{type:'miniclaw.director.return',workspace:'fixture',target:'photo',task:'image-edit'}};
  listeners.message({...event,source:{}});expect(app.closeDirector).not.toHaveBeenCalled();
  listeners.message(event);expect(app.closeDirector).toHaveBeenCalledOnce();
  expect(app.choose).toHaveBeenCalledWith('photo');expect(app.imagePanel).toBe('photo');expect(app.composerExpanded).toBe(true);
  expect(app.revealComposerTarget).toHaveBeenCalledOnce();expect(asset.imageModel).toBe('chosen-model');expect(asset.imagePrompt).toBe('确认后的要求');
});

test('late context acknowledgements never reopen a hidden shared frame',()=>{
  const listeners={},frame={};
  const base={init(){},$watch:vi.fn(),choose:vi.fn(),$refs:{director:{contentWindow:frame}},workspaceId:'fixture',$nextTick:fn=>fn()};
  const context={base,location:{origin:'http://localhost'},window:{innerWidth:1280,addEventListener:(type,fn)=>listeners[type]=fn}};
  const app=runInNewContext(readFileSync(new URL('../public/studio/interaction.js',import.meta.url),'utf8')+';withStudioInteraction(base)',context);
  app.init();app.promptAdvice=true;app.directorFrameUrl='/?director=fixture';app.closeDirector();
  listeners.message({origin:'http://localhost',source:frame,data:{type:'miniclaw.director.context',workspace:'fixture',request:app.directorRequest,target:'photo',label:'图片',intent:'optimize-edit',pending:false}});
  expect(app.assistant).toBe(false);expect(app.promptAdvice).toBe(false);expect(app.directorFrameUrl).toBe('/?director=fixture');
});

test('canvas selections append references to the existing frame rather than switch chat targets',async()=>{
  const app=studio();const postMessage=vi.fn();app.$refs.director={contentWindow:{postMessage}};
  app.projectReady=true;app.assistant=true;app.directorFrameUrl='persistent-frame';app.flushProject=vi.fn(async()=>{});app.openDirectorSelection=vi.fn();
  app.choose('s1');app.choose('source');await vi.waitFor(()=>expect(postMessage).toHaveBeenCalledTimes(2));
  expect(postMessage.mock.calls.map(([data])=>data.target)).toEqual(['s1','source']);
  expect(postMessage.mock.calls.every(([data])=>data.type==='miniclaw.director.reference')).toBe(true);
  expect(app.openDirectorSelection).not.toHaveBeenCalled();expect(app.directorFrameUrl).toBe('persistent-frame');
});
