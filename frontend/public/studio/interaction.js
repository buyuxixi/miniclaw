/* Explicit object context and resilient selectors for the creative workbench. */
const interactionFilm=window.film;
window.film=function(){
  const app=interactionFilm(),init=app.init,choose=app.choose;
  Object.assign(app,{workspaceMenu:false,workspaceQuery:'',workspaceListBusy:false,workspaceListError:'',workspaceSwitching:false,compactViewport:window.innerWidth<=600,modelListBusy:false,modelListError:'',
    versionCategory:'all',versionDetails:{},versionsError:'',directorFrameUrl:'',directorContext:null,directorConfirmed:null,directorStatus:'',directorRequest:0,directorAdopting:false,composerMore:false,directorFraming:false});
  Object.defineProperties(app,Object.getOwnPropertyDescriptors({
    init(){init.call(this);window.addEventListener('resize',()=>{this.compactViewport=window.innerWidth<=600;this.$nextTick(()=>this.sizeProjectFacts());});window.addEventListener('message',e=>{
      if(e.origin!==location.origin||e.source!==this.$refs.director?.contentWindow||e.data?.workspace!==this.workspaceId)return;
      if(e.data.type==='miniclaw.director.adopt-prompt'){void this.adoptDirectorPrompt(e.data);return;}
      if(e.data.type==='miniclaw.director.adopt-image-prompt'){void this.adoptDirectorImagePrompt(e.data);return;}
      if(e.data.type==='miniclaw.director.return'){this.closeDirector();this.$nextTick(()=>this.$refs.composer?.querySelector('.composer-prompt')?.focus());return;}
      if(e.data.type==='miniclaw.director.ready'){this.syncDirectorTarget();return;}
      if(e.data.type!=='miniclaw.director.context')return;
      if(e.data.request!==this.directorRequest)return;
      this.directorConfirmed={target:e.data.target,label:e.data.label};this.directorStatus=e.data.pending?'pending':'confirmed';
    });},
    choose(id,event){choose.call(this,id,event);this.composerMore=false;if(this.assistant&&this.selectedIds.length===1&&this.getTarget(this.selection))void this.openDirectorSelection(this.directorContext?.intent||'discuss');},
    async loadWorkspaceList(){if(this.workspaceListBusy)return;this.workspaceListBusy=true;this.workspaceListError='';try{
      const r=await fetch('/api/workspaces',{headers:{'X-Hermes-Session-Token':window.WORKSPACE_TOKEN},signal:AbortSignal.timeout(15000)});
      if(!r.ok)throw Error('项目列表暂时无法读取');const rows=await r.json();if(!Array.isArray(rows))throw Error('项目列表格式无效');this.workspaceList=rows;
    }catch(e){this.workspaceListError=e.message;}finally{this.workspaceListBusy=false;}},
    get searchedWorkspaces(){const q=this.workspaceQuery.trim().toLowerCase();return this.workspaceList.filter(p=>(shortStudioName(p.name)+' '+p.id).toLowerCase().includes(q));},
    async loadModels(){if(this.modelListBusy)return;this.modelListBusy=true;this.modelListError='';try{this.modelCatalog=(await this.projectApi('/models')).models;this.composerError='';this.measureModelMenu();}catch(e){this.modelListError=e.message;}finally{this.modelListBusy=false;}},
    workspaceDescription(p){const at=p.updated_at||p.updated;return (at?new Date(at*1000).toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'})+' · ':'')+p.id.slice(-6);},
    toggleWorkspaceMenu(){this.workspaceMenu=!this.workspaceMenu;if(this.workspaceMenu){this.workspaceQuery='';void this.loadWorkspaceList();this.$nextTick(()=>this.$refs.workspaceSearch?.focus());}},
    async switchWorkspace(event){const id=typeof event==='string'?event:event.target.value;if(id===this.workspaceId){this.workspaceMenu=false;return;}if(this.workspaceSwitching)return;this.workspaceSwitching=true;try{await this.flushProject();location.href='/studio/index.html?workspace='+encodeURIComponent(id);}catch(e){this.projectError='切换前保存未完成：'+e.message;}finally{this.workspaceSwitching=false;}},
    frameDirectorView(update){this.directorFraming=true;this.$nextTick(()=>{update();setTimeout(()=>this.directorFraming=false,220);});},
    closeDirector(){this.assistant=false;this.directorRequest++;this.directorStatus='';this.directorFrameUrl='';},
    closeSurface(){if(this.workspaceMenu){this.workspaceMenu=false;this.$refs.workspaceTrigger?.focus();return;}if(this.composerMore){this.composerMore=false;this.$refs.composerMoreTrigger?.focus();return;}if(this.modelMenu||this.referenceMenu||this.addMenu){this.modelMenu=false;this.referenceMenu=false;this.addMenu=false;return;}if(this.fullEditor)this.closeFullEditor();else{this.panel='';this.closeDirector();}},
    focusComposerAction(direction=1){const actions=[...this.$refs.composerMore.querySelectorAll('button,a')].filter(el=>el.offsetParent&&!el.disabled);if(!actions.length)return;const at=actions.indexOf(document.activeElement);actions[(at+direction+actions.length)%actions.length].focus();},
    toggleComposerMore(){this.composerMore=!this.composerMore;if(this.composerMore)this.$nextTick(()=>this.focusComposerAction());},
    sizeProjectFacts(){const input=this.$refs.projectFacts;if(!input||this.panel!=='project'||this.projectTab!=='overview')return;if(window.innerWidth>760){input.style.removeProperty('height');return;}input.style.height='auto';input.style.height=Math.max(120,input.scrollHeight+input.offsetHeight-input.clientHeight)+'px';},
    setProjectTab(tab){this.projectTab=tab;this.$nextTick(()=>{const scroll=document.querySelector('.project-scroll');if(scroll)scroll.scrollTop=0;this.sizeProjectFacts();});if(tab==='versions')void this.loadContentVersions();},
    get versionCategories(){return [{id:'all',name:'全部内容'},{id:'image',name:'图片'},{id:'copy',name:'文案与创意'},{id:'narration',name:'口播'},{id:'video',name:'视频与镜头'},{id:'render',name:'成片'}];},
    categoryForVersion(v){return v.target==='narration'||v.id==='narration'?'narration':v.kind==='image'?'image':['prompt','video'].includes(v.kind)?'video':v.kind==='render'?'render':'copy';},
    get categoryVersionTargets(){return this.searchedVersionTargets.filter(t=>this.versionCategory==='all'||this.contentVersionTargets.some(v=>v.id===t.id&&this.categoryForVersion(v)===this.versionCategory));},
    selectVersionCategory(id){this.versionCategory=id;this.versionTarget='';void this.loadContentVersions();},
    async loadContentVersions(more=false){if(more&&this.versionsBusy)return;const request=++this.versionRequest;this.versionsBusy=true;this.versionsError='';if(!more){this.contentVersions=[];this.versionTotal=0;}try{
      const r=await this.projectApi('/versions?page='+(more?this.versionPage+1:1)+'&target='+encodeURIComponent(this.versionTarget)+'&category='+this.versionCategory);
      if(request!==this.versionRequest)return;this.contentVersions=more?[...this.contentVersions,...r.items.filter(v=>!this.contentVersions.some(old=>old.id===v.id))]:r.items;this.contentVersionTargets=r.targets;this.versionPage=r.page;this.versionTotal=r.total;
      if(!more)this.$nextTick(()=>{const body=document.querySelector('.version-history');if(body)body.scrollTop=0;});
    }catch(e){if(request===this.versionRequest)this.versionsError=e.message;}finally{if(request===this.versionRequest)this.versionsBusy=false;}},
    async loadVersionDetail(v,open){if(!open||this.versionDetails[v.id]?.text||this.versionDetails[v.id]?.busy)return;this.versionDetails[v.id]={busy:true};try{const r=await this.projectApi('/versions/'+encodeURIComponent(v.id));this.versionDetails[v.id]={text:r.data.text||v.data.text};}catch(e){this.versionDetails[v.id]={error:e.message};}},
    resolveDirectorContext(){const id=this.selectedIds.length===1?this.selection:'',job=this.videoJobs.find(j=>'video-'+j.id===id),shot=this.shots.find(s=>s.id===(job?.shot||id)),asset=this.assets.find(a=>a.id===id),note=this.notes.find(n=>n.id===id);
      return {target:shot?.id||asset?.id||note?.id||'',node:id,label:shot?shot.name+(job?' · 视频结果':' · 镜头设置'):asset?'图片 · '+asset.name:note?'创意 · '+note.title:'当前项目',kind:shot?'shot':asset?'image':'project',result:job?.id||'',intent:'discuss'};
    },
    get directorUrl(){return this.directorFrameUrl;},
    ask(){void this.openDirectorSelection();},
    askSelection(){void this.openDirectorSelection();},
    async openDirectorSelection(intent='discuss'){
      this.modelMenu=false;this.referenceMenu=false;this.composerMore=false;
      const context={...this.resolveDirectorContext(),intent},request=++this.directorRequest;this.directorContext=context;this.directorStatus='saving';
      try{await this.flushProject();if(request!==this.directorRequest)return;
        if(!this.assistant||!this.directorFrameUrl)this.directorFrameUrl='/?director='+encodeURIComponent(this.workspaceId)+'&target='+encodeURIComponent(context.target)+'&label='+encodeURIComponent(context.label)+'&intent='+intent;
        this.quote={targetId:context.target,label:context.label};this.assistant=true;this.directorStatus='connecting';this.syncDirectorTarget();
      }catch(e){this.composerError='导演上下文尚未同步：'+e.message;this.directorStatus='error';}
    },
    syncDirectorTarget(){this.$nextTick(()=>{if(this.directorContext)this.$refs.director?.contentWindow.postMessage({type:'miniclaw.director.target',workspace:this.workspaceId,...this.directorContext,request:this.directorRequest},location.origin);});},
    async adoptDirectorPrompt(message){const reply=(ok,error='')=>this.$refs.director?.contentWindow.postMessage({type:'miniclaw.director.prompt-result',workspace:this.workspaceId,request:message.request,ok,error},location.origin);
      if(this.directorAdopting){reply(false,'正在采用，请等待完成');return;}
      this.directorAdopting=true;
      try{const shot=this.shots.find(s=>s.id===message.shot);if(!shot||this.directorConfirmed?.target!==shot.id)throw Error('导演对象已变化，请重新选中镜头');
        if(shot.prompt!==message.before)throw Error('镜头提示词已修改，建议仍保留，请重新优化后比较');
        await this.flushProject();if(shot.prompt!==message.before)throw Error('镜头提示词已修改，建议仍保留，请重新比较');
        const record=await this.projectApi('/commands',{request_id:message.request,revision:this.projectRevision,action:'shot-plan',args:{owner:message.owner,message:message.message,shot:shot.id,expected_prompt:message.before}});
        for(const [key,value] of Object.entries(record.state))this[key]=value;this.projectRevision=record.revision;this.projectEvents=record.events;this._ack=JSON.stringify(this.projectSnapshot());this.persist();reply(true);this.notify('提示词已采用 · 点击生成得到新视频');
      }catch(e){reply(false,e.message);}finally{this.directorAdopting=false;}
    },
    async adoptDirectorImagePrompt(message){const reply=(ok,error='')=>this.$refs.director?.contentWindow.postMessage({type:'miniclaw.director.prompt-result',workspace:this.workspaceId,request:message.request,ok,error},location.origin);
      if(this.directorAdopting){reply(false,'正在保存，请等待完成');return;}
      this.directorAdopting=true;
      try{
        if(!['image-edit','image-generate'].includes(message.task)||typeof message.prompt!=='string'||!message.prompt.trim()||message.prompt.length>2000)throw Error('优化建议格式不完整');
        const check=()=>{const asset=this.assets.find(a=>a.id===message.target);if(!asset||this.directorConfirmed?.target!==asset.id||asset.file!==message.file)throw Error('图片已变化，请重新选中后优化');if((asset.imagePrompt||'')!==message.before&&asset.imagePrompt!==message.prompt)throw Error('图片提示词已修改，建议仍保留，请重新比较');return asset;};
        check();await this.flushProject();const asset=check();
        if(asset.imagePrompt!==message.prompt){this.remember();asset.imagePrompt=message.prompt;if(message.task==='image-edit')asset.imageEditPrompt=message.prompt;this.persist();}
        await this.flushProject();check();reply(true);this.notify('提示词已保存 · 可继续调整或提交修图');
      }catch(e){reply(false,e.message);}finally{this.directorAdopting=false;}
    },
  }));return app;
};
