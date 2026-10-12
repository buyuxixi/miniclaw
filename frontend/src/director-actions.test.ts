// @vitest-environment jsdom
import {expect,test,vi} from 'vitest';
import {directImageAction,flipDirectorImage,singleShotPrompt,adoptDirectorPrompt,singleImagePrompt} from './director-actions';
import {shotOptimizationMessage,imageOptimizationMessage} from './fixtures/legacy-director-prompts';
test('image feedback optimization acknowledges attached pixels without treating the screenshot as a new working image',()=>{
  const message=imageOptimizationMessage({name:'人像',prompt:'眼角加痣'},'看红框','image-edit',true);
  expect(message).toContain('结合图片判断');expect(message).toContain('不默认替换当前工作图');expect(message).not.toContain('这里没有图片像素');
});
import {loadProject} from './canvas-api';
import {writeApi} from './management-api';
vi.mock('./canvas-api',async()=>({...await vi.importActual('./canvas-api'),loadProject:vi.fn()}));
vi.mock('./management-api',()=>({writeApi:vi.fn()}));

test('image optimization validates task and bounded text and separates advice from generation',()=>{
  const format=(v:unknown)=>'```product-prompt\n'+JSON.stringify(v)+'\n```';
  const candidate={task:'image-edit',prompt:'产品向左倾斜30°，仅压暗背景，包装标识保持'};
  expect(singleImagePrompt(format(candidate),'image-edit')).toBe(candidate.prompt);
  for(const v of [{...candidate,task:'video'},{...candidate,execute:true},{...candidate,prompt:''},{...candidate,prompt:'x'.repeat(2001)}])expect(singleImagePrompt(format(v),'image-edit')).toBeNull();
  expect(singleImagePrompt(format(candidate),'image-generate')).toBeNull();expect(singleImagePrompt(format(candidate)+format(candidate),'image-edit')).toBeNull();
  const message=imageOptimizationMessage({name:'洗面奶',prompt:'背景略暗'},'包装不动','image-edit');
  expect(message).toContain('不调用工具');expect(message).toContain('不执行修图');expect(message).toContain('image-edit');expect(message).toContain('背景略暗');
});
test('prompt previews accept exactly one backend-compatible shot and reject malformed or oversized advice',()=>{
  const plan=(shots:unknown[])=>'```studio-plan\n'+JSON.stringify({shots})+'\n```';const shot={name:'泥膜',duration:5,prompt:'产品不动，泥膜缓慢流动'};
  expect(singleShotPrompt(plan([shot]))).toBe(shot.prompt);
  for(const shots of [[],[shot,shot],[{...shot,prompt:'x'.repeat(1501)}],[{...shot,duration:10}],[{...shot,prompt:5}],[{...shot,execute:true}]])expect(singleShotPrompt(plan(shots))).toBeNull();
  expect(singleShotPrompt('```studio-plan\n{broken\n```')).toBeNull();
  const message=shotOptimizationMessage({name:'泥膜',prompt:'泥膜静止。泥膜强烈流动'},'流动更明显');expect(message).toContain('移除旧提示词');expect(message).toContain('不生成视频');expect(message).toContain('流动更明显');
});
test('adoption waits for the exact parent acknowledgement rather than sending around unsaved canvas edits',async()=>{
  const post=vi.spyOn(window,'postMessage').mockImplementation(()=>{});const pending=adoptDirectorPrompt('workspace',{target:'shot',prompt:'original'},'owner',2);const sent=post.mock.calls.at(-1)![0];expect(sent.before).toBe('original');expect(sent.type).toBe('miniclaw.director.adopt-prompt');
  let done=false;void pending.then(()=>{done=true;});window.dispatchEvent(new MessageEvent('message',{origin:location.origin,source:window,data:{type:'miniclaw.director.prompt-result',workspace:'other',request:sent.request,ok:true}}));await Promise.resolve();expect(done).toBe(false);
  window.dispatchEvent(new MessageEvent('message',{origin:location.origin,source:window,data:{type:'miniclaw.director.prompt-result',workspace:'workspace',request:sent.request,ok:true}}));await pending;expect(done).toBe(true);post.mockRestore();
});
test('only clear single flip requests execute directly',()=>{
  for(const text of ['水平翻转','帮我把这张图片水平翻转一下','请进行一个水平翻转','做一个水平翻转的操作','水平镜像']){
    expect(directImageAction(text)).toBe('horizontal');
  }
  expect(directImageAction('垂直翻转')).toBe('vertical');
  for(const text of ['不要水平翻转','水平翻转，然后调亮','看看水平翻转是否合适','水平翻转两次'])expect(directImageAction(text)).toBeNull();
});
test('flip submits one local edit to the selected layer and rejects changed/locked targets',async()=>{
  vi.clearAllMocks();const project={id:'image-project',revision:7,document:{layers:[{id:'chosen',kind:'image',locked:false},{id:'other',kind:'image',locked:false}]}} as any;
  vi.mocked(loadProject).mockResolvedValue({project} as any);vi.mocked(writeApi).mockResolvedValue({...project,revision:8});
  expect((await flipDirectorImage(project,'chosen','horizontal')).revision).toBe(8);
  expect(writeApi).toHaveBeenCalledExactlyOnceWith('/api/miniclaw/canvas/projects/image-project/local','POST',{revision:7,layer_id:'chosen',operation:'flip',params:{direction:'horizontal'}});
  vi.mocked(loadProject).mockResolvedValue({project:{...project,revision:8}} as any);await expect(flipDirectorImage(project,'chosen','horizontal')).rejects.toThrow('已更新');expect(writeApi).toHaveBeenCalledTimes(1);
  project.document.layers[0].locked=true;vi.mocked(loadProject).mockResolvedValue({project} as any);await expect(flipDirectorImage(project,'chosen','horizontal')).rejects.toThrow('可编辑');expect(writeApi).toHaveBeenCalledTimes(1);
});
