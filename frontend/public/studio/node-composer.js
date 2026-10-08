/* Media nodes stay on the canvas. Controls belong to the selected task. */
const mediaFilm=window.film;
function studioCurvePath(segments){return 'M '+segments[0].x+' '+segments[0].y+segments.slice(1).map(([a,b,c])=>' C '+a.x+' '+a.y+', '+b.x+' '+b.y+', '+c.x+' '+c.y).join('');}
window.film=function(){
  const app=mediaFilm(),load=app.loadSharedProject,refresh=app.refreshVideo,choose=app.choose,init=app.init;
  const routes=new Map();
  Object.assign(app,{modelCatalog:[],modelMenu:false,imagePanel:'',imageBusy:false,composerError:'',referenceMenu:false,composerHeight:320,toolbarWidth:400,modelMenuHeight:400,modelMenuStyle:{},referenceMenuStyle:{},assemblyClip:''});
  Object.defineProperties(app,Object.getOwnPropertyDescriptors({
    init(){init.call(this);this.$watch('selection',()=>{this.modelMenu=false;this.referenceMenu=false;this.composerError='';});
      const positionMenu=()=>this.$nextTick(()=>{if(this.modelMenu)this.measureModelMenu();if(this.referenceMenu)this.referenceMenuStyle=this.popupStyle(this.$refs.referenceTrigger,280,260);});this.$watch('modelMenu',positionMenu);this.$watch('referenceMenu',positionMenu);this.$watch('zoom',positionMenu);this.$watch('pan',positionMenu);window.addEventListener('resize',positionMenu);
      this.$nextTick(()=>{if(typeof ResizeObserver==='undefined')return;const measure=(ref,key,dimension)=>{const element=this.$refs[ref];if(!element)return;new ResizeObserver(()=>{const value=element[dimension];if(value>0&&this[key]!==value)this[key]=value;positionMenu();}).observe(element);};measure('composer','composerHeight','offsetHeight');measure('contextToolbar','toolbarWidth','offsetWidth');});},
    async loadSharedProject(){await load.call(this);if(!this.projectReady)return;try{this.modelCatalog=(await this.projectApi('/models')).models;await this.refreshImages();}catch(e){this.composerError=e.message;}},
    choose(id,event){choose.call(this,id,event);this.modelMenu=false;this.referenceMenu=false;},
    get hasCanvasSelection(){return this.selectedIds.includes(this.selection)&&!!this.getTarget(this.selection);},
    get showContextToolbar(){return this.hasCanvasSelection&&(this.selectedIds.length!==1||!this.composerTask);},
    clearCanvasSelection(){this.selection='';this.selectedIds=[];this.imagePanel='';this.modelMenu=false;this.referenceMenu=false;this.selectedEdge=null;this.addMenu=false;this.composerError='';},
    backgroundClick(){if(!this.dragClick){this.clearCanvasSelection();this.persist();}},
    get composerShot(){if(!this.hasCanvasSelection)return;return this.shots.find(s=>s.id===this.selection)||this.shots.find(s=>s.id===this.videoJobs.find(j=>'video-'+j.id===this.selection)?.shot);},
    get composerAsset(){return this.hasCanvasSelection?this.assets.find(a=>a.id===this.selection):undefined;},
    get composerTask(){if(this.composerShot)return 'video';if(this.composerAsset?.generationDraft)return 'generate';return this.composerAsset&&this.imagePanel===this.selection?'edit':'';},
    get composerImageJob(){return this.composerAsset?.imageJob?.task===this.composerTask?this.composerAsset.imageJob:null;},
    get composerObject(){return this.composerShot||this.composerAsset;},
    modelsFor(task){return this.modelCatalog.filter(m=>m.tasks.includes(task));},
    popupStyle(trigger,width,height){if(!trigger)return {};const rect=trigger.getBoundingClientRect(),world=this.$refs.world,viewWidth=window.innerWidth||world.clientWidth,viewHeight=window.innerHeight||world.clientHeight,gap=8,above=rect.top-74-gap,below=viewHeight-rect.bottom-16-gap,up=above>=below;
      // Anchor the near edge; maxHeight limits scrolling, not the actual menu height.
      width=Math.min(width,viewWidth-32);height=Math.max(40,Math.min(height,up?above:below));return {position:'fixed',left:Math.max(16,Math.min(rect.left,viewWidth-width-16))+'px',top:up?'auto':(rect.bottom+gap)+'px',bottom:up?(viewHeight-rect.top+gap)+'px':'auto',width:width+'px',maxWidth:width+'px',maxHeight:height+'px'};},
    measureModelMenu(){this.modelMenuStyle=this.popupStyle(this.$refs.modelTrigger,320,400);this.modelMenuHeight=parseFloat(this.modelMenuStyle.maxHeight)||400;},
    selectedModel(task=this.composerTask,obj=this.composerObject){if(!obj)return {};const provider=task==='video'?obj.videoProvider:obj.imageProvider,model=task==='video'?obj.videoModel:obj.imageModel;
      return this.modelsFor(task).find(m=>m.provider===provider&&m.model===model)||this.modelsFor(task).find(m=>m.provider===provider&&m.model===(task==='video'?this.providerFor(obj).model:''))||this.modelsFor(task).find(m=>m.configured)||this.modelsFor(task)[0]||{};},
    composerEstimate(){const m=this.selectedModel();if(m.reference_unit_cny==null)return '费用待核对';const duration=this.composerTask==='video'?m.duration:1;let amount=m.reference_unit_cny*duration;if(this.composerTask==='video'&&this.composerShot?.mode==='reference'){const free=m.model==='MiniMax-H3'?5:2;amount+=Math.max(0,this.composerRefs().length-free)*(m.model==='MiniMax-H3'?.2:.5);}return '预估 ¥'+amount.toFixed(3).replace(/0$/,'');},
    setModel(option){const obj=this.composerObject;if(!obj||!option.configured)return;this.remember();if(this.composerTask==='video'){obj.videoProvider=option.provider;obj.videoModel=option.model;obj.dirty=true;}else{obj.imageProvider=option.provider;obj.imageModel=option.model;}this.modelMenu=false;this.composerError='';this.persist();},
    mediaSize(){return {w:238,h:423};},
    panelAnchor(){if(!this.hasCanvasSelection)return null;const id=this.selection,n=this.getTarget(id);const asset=this.assets.find(a=>a.id===id);return {...n,w:asset?.w||this.mediaSize().w,h:asset?asset.h+34:this.mediaSize().h+34};},
    floatingStyle(kind){const n=this.panelAnchor(),world=this.$refs.world;if(!n||!world)return {};const margin=16,w=Math.min(kind==='composer'?540:this.toolbarWidth,Math.max(240,world.clientWidth-margin-16));let left=Math.max(margin,Math.min(world.clientWidth-w-16,this.pan.x+(n.x+n.w/2)*this.zoom-w/2));
      const nodeTop=this.pan.y+n.y*this.zoom,nodeBottom=this.pan.y+(n.y+n.h)*this.zoom;
      let top=kind==='toolbar'?Math.max(12,Math.min(world.clientHeight-68,nodeTop-50)):Math.max(12,Math.min(world.clientHeight-this.composerHeight-68,nodeBottom+16));
      if(kind==='composer'&&nodeBottom+16+this.composerHeight>world.clientHeight-68){const nodeLeft=this.pan.x+n.x*this.zoom,nodeRight=nodeLeft+n.w*this.zoom;if(nodeRight+16+w<=world.clientWidth-16)left=nodeRight+16;else if(nodeLeft-w-16>=margin)left=nodeLeft-w-16;else if(nodeTop-this.composerHeight-16>=12)top=nodeTop-this.composerHeight-16;}
      left=Math.max(margin,Math.min(world.clientWidth-w-16,left));
      // Bind only positioning properties so Alpine's x-show keeps ownership of display.
      return {left:left+'px',top:top+'px',maxWidth:(kind==='composer'?w:world.clientWidth-margin-16)+'px',width:kind==='composer'?w+'px':'max-content'};},
    shotPreview(s){return this.displayFile(this.assets.find(a=>a.id===(s.mode==='first'?s.first:s.refs?.[0]))?.file||'');},
    shotVideo(s){return this.latestShotJob(s)?.media||'';},
    shotPoster(s){return this.displayFile(this.latestShotJob(s)?.image||this.assets.find(a=>a.id===(s.mode==='first'?s.first:s.refs?.[0]))?.file||'');},
    composerRefs(){const s=this.composerShot;return s?(s.mode==='first'?[s.first]:s.refs).map(id=>this.assets.find(a=>a.id===id)).filter(a=>a&&!a.pending):this.composerTask==='edit'?[this.composerAsset]:[];},
    addReference(id){const s=this.composerShot;if(!s)return;this.connectNodes(id,s.id);this.referenceMenu=false;},
    setInputMode(mode){const s=this.composerShot;if(!s||s.mode===mode)return;this.remember();if(mode==='reference')s.refs=[...new Set([s.first,...(s.refs||[])].filter(Boolean))];else s.first=s.first||s.refs?.[0]||'';s.mode=mode;s.dirty=true;this.persist();},
    get referenceWarning(){const s=this.composerShot;return s?.mode==='reference'&&!this.selectedModel().references?'此模型支持首帧生成；多图参考请选择 MiniMax H3 / H3 Max。':'';},
    get assemblyPreview(){return this.currentRender?.media||this.videoSequence.find(s=>s.job===this.assemblyClip)?.video?.media||this.videoSequence[0]?.video?.media||'';},
    startImageEdit(){this.imagePanel=this.selection;this.composerAsset.imagePrompt=this.composerAsset.imageEditPrompt||this.edits[this.selection]?.text||'';this.modelMenu=false;},
    addImageGeneration(){this.remember();const id='image-'+crypto.randomUUID(),pos=this.freePosition(430,40,250,350);this.assets.push({id,name:'新的图片',pending:true,generationDraft:true,purpose:'图片生成',w:250,h:300,...pos,imagePrompt:'',imageProvider:'dashscope',imageModel:'qwen-image-max'});this.choose(id);this.addMenu=false;this.persist();this.focusObject(id);},
    makeVideoFromImage(){const a=this.composerAsset;if(!a||a.pending)return;this.addShot();this.shot.first=a.id;this.shot.x=a.x+a.w+260;this.shot.y=a.y;this.persist();this.focusShot();},
    async canvasApi(path,body){const r=await fetch('/api/miniclaw/canvas'+path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json','X-Hermes-Session-Token':window.WORKSPACE_TOKEN},body:body?JSON.stringify(body):undefined,cache:'no-store'});const data=await r.json();if(!r.ok)throw Error(data.detail||'图片任务读取失败');return data;},
    async submitComposer(){if(this.composerTask==='video'){const s=this.composerShot,m=this.selectedModel();if(!m.configured){this.composerError='请先配置这个模型的 API Key';return;}s.videoProvider=m.provider;s.videoModel=m.model;this.active=s.id;await this.generateVideo();if(!this.videoError){this.panel='';this.choose(s.id);}else this.composerError=this.videoError;return;}
      const a=this.composerAsset,task=this.composerTask,m=this.selectedModel();if(!a||!task||this.imageBusy)return;this.imageBusy=true;this.composerError='';
      try{a.imageProvider=m.provider;a.imageModel=m.model;await this.flushProject();const key=JSON.stringify([task,a.id,a.file,a.imagePrompt,m.provider,m.model,this.projectRevision]),storage='studio-image-request:'+this.workspaceId+':'+a.id;let pending;try{pending=JSON.parse(localStorage.getItem(storage)||'null')}catch{}
        if(!pending||pending.key!==key)pending={key,body:{request_id:crypto.randomUUID(),revision:this.projectRevision,object:a.id,task,provider:m.provider,model:m.model,prompt:a.imagePrompt||''}};
        localStorage.setItem(storage,JSON.stringify(pending));a.imageJob=await this.projectApi('/images',pending.body);localStorage.removeItem(storage);this.persist();
      }catch(e){this.composerError=e.message;}finally{this.imageBusy=false;}},
    async refreshVideo(){await refresh.call(this);await this.refreshImages();},
    async refreshImages(){for(const a of this.assets.filter(a=>a.imageJob&&['queued','running'].includes(a.imageJob.state))){try{const job=await this.projectApi('/images/'+a.imageJob.request_id);if(JSON.stringify(a.imageJob)!==JSON.stringify(job)){a.imageJob=job;this.persist();}}catch(e){this.composerError=e.message;}}},
    async adoptComposerImage(){const a=this.composerAsset,c=this.composerImageJob;if(!c?.output)return;if(c.task==='edit'){this.editSource=JSON.parse(JSON.stringify(a));this.editAssetId=a.id;this.editorProject=c.project;this.editorCandidate={...c,job:{id:c.job}};this.compareBasis=this.projectRevision;this.adoptShot=null;this.adoptRequest=null;this.previewBefore='';this.editorUrl='';this.editorLoading=false;this.editorFailure='';this.fullEditor=true;await this.refreshEditorComparison();return;}
      this.remember();a.file=c.output;a.pending=false;a.generationDraft=false;a.editProject=c.project;a.h=Math.min(500,a.w*c.height/c.width);a.name=a.imagePrompt?.slice(0,24)||'生成图片';this.persist();await this.flushProject();this.notify('图片已加入画布，可连接视频节点');},
    latestMatchingJob(s){const m=this.selectedModel('video',s);return this.videoJobs.filter(j=>j.shot===s.id&&!j.stale&&j.model===m.model&&j.provider===m.provider).at(-1);},
    composerBusy(){const j=this.composerTask==='video'?this.latestMatchingJob(this.composerShot):this.composerAsset?.imageJob;return this.videoBusy||this.imageBusy||['queued','submitting','running','unknown'].includes(j?.state);},
    composerProgress(){const j=this.composerTask==='video'?this.latestMatchingJob(this.composerShot):this.composerImageJob;if(this.imageBusy||this.videoBusy)return '正在提交…';if(this.composerTask!=='video'&&j?.state==='succeeded'&&j.model){const m=this.selectedModel(),label=this.modelCatalog.find(o=>o.provider===j.provider&&o.model===j.model)?.label||j.model;return (m.model!==j.model||m.provider!==j.provider?'上次结果':'结果已生成')+' · '+label;}return {queued:'任务排队中',submitting:'正在提交…',running:this.composerTask==='edit'?'正在修图':this.composerTask==='video'?'正在生成视频':'正在生成图片',unknown:'正在确认任务状态',succeeded:'结果已生成',failed:'生成失败',canceled:'已停止接收'}[j?.state]||'';},
    edgeGeometry(e,scene){const a=scene?.ports?.get(e.from+':out')||this.portPoint(e.from,'out'),b=scene?.ports?.get(e.to+':in')||this.portPoint(e.to,'in'),d=Math.max(60,Math.min(240,Math.abs(b.x-a.x)*.4));
      // A connection follows its two ports. Neither nodes nor floating UI reroute it.
      const key=JSON.stringify([a,b]),id=e.id||e.from+'>'+e.to,cached=routes.get(id);if(cached?.key===key)return cached.geometry;
      const geometry={path:studioCurvePath([a,[{x:a.x+d,y:a.y},{x:b.x-d,y:b.y},b]])};routes.set(id,{key,geometry});return geometry;},
    portPoint(id,side){const n=this.getTarget(id);if(!n)return {x:0,y:0};const asset=this.assets.find(a=>a.id===id),note=this.notes.find(n=>n.id===id);return {x:n.x+(side==='out'?(asset?.w||note?.w||this.mediaSize().w):0),y:n.y+(asset?34+asset.h/2:note?100:34+this.mediaSize().h/2)};},
    objects(){const size=this.mediaSize();return this.assets.map(a=>({...a,h:a.h+60})).concat(this.notes,this.shots.map(s=>({...s,w:size.w,h:size.h+34})),this.visibleVideoJobs.map(j=>({...this.videoPosition(j),id:'video-'+j.id,w:size.w,h:size.h+34})),this.narrationNode.removed?[]:[{...this.narrationNode,id:'narration',w:300,h:110}]);},
  }));return app;
};
