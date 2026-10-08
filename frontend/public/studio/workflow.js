async function studioBackupDatabase(workspace,value){
  if(typeof indexedDB==='undefined')throw Error('备份存储不可用');
  const db=await new Promise((resolve,reject)=>{const request=indexedDB.open('studio-project-backups',1);request.onupgradeneeded=()=>request.result.createObjectStore('backups');request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);request.onblocked=()=>reject(Error('备份存储被其他页面占用'));});
  try{return await new Promise((resolve,reject)=>{const transaction=db.transaction('backups',value===undefined?'readonly':'readwrite'),store=transaction.objectStore('backups');let result;
    const request=value===undefined?store.get(workspace):store.put(value,workspace);request.onsuccess=()=>{result=value===undefined?request.result:value;};transaction.oncomplete=()=>resolve(result);transaction.onerror=transaction.onabort=()=>reject(transaction.error||Error('备份未完成'));});}finally{db.close();}
}
/* The free canvas hosts the existing complete image editor. The editable
   document is saved independently; only explicit adoption changes an input. */
function usableCanvas(app) {
  app=baseUsableCanvas(app);
  const init=app.init, keydown=app.keydown, persist=app.persist, saveClip=app.saveClip;
  let projectRead=null;
  const fields=['assets','shots','edits','narration','voice','review','sequence','saved','messages','candidate','notes','narrationNode','facts','canvasLayout'];
  Object.assign(app,{fullEditor:false,editorUrl:'',editorToken:'',editorProject:'',editorLoading:false,editorReady:false,
    editorFailure:'',editorCandidate:null,editorApplying:false,projectReady:false,projectLoading:true,projectRevision:0,
    projectPreview:false,projectStatus:'正在读取项目',projectError:'',projectConflict:false,projectBackupAvailable:false,projectBackupTime:0,projectEvents:[],projectTasks:[],facts:'',canvasLayout:{},_ack:'',_pendingRequest:null});
  Object.defineProperties(app,Object.getOwnPropertyDescriptors({
    init(){init.call(this);if(this.panel==='edit')this.panel='';if(typeof matchMedia==='function'&&matchMedia('(max-width:600px)').matches&&this.shots.length)this.choose(this.active||this.shots[0].id);this.readProjectPreview();void this.loadSharedProject().then(()=>{const state=new URLSearchParams(location.search).get('state');if(state==='precision'||state==='edit')void this.openEdit();if(state==='project')void this.showProject()});window.addEventListener('focus',()=>{if(this.projectReady&&!this.directorAdopting&&!this.panel&&!this.fullEditor&&!this.drag&&JSON.stringify(this.projectSnapshot())===this._ack)void this.loadSharedProject()});window.addEventListener('message',event=>{
      if(!this.fullEditor||event.origin!==location.origin||event.source!==this.$refs.fullEditor?.contentWindow)return;
      const message=event.data;
      if(message?.type!=='miniclaw.precision'||message.nonce!==this.editorToken||message.project!==this.editorProject)return;
      if(message.action==='ready'){this.editorReady=true;this.editorLoading=false;clearTimeout(this._editorTimer)}
      if(message.action==='close')this.closeFullEditor();
      if(message.action==='review')void this.reviewFullEditor(message.revision);
    })},
    projectSnapshot(){return Object.fromEntries(fields.map(key=>[key,JSON.parse(JSON.stringify(this[key]))]))},
    cacheProjectView(){try{localStorage.setItem('video-workspace-03',JSON.stringify({workspaceId:this.workspaceId,active:this.active,selection:this.selection,history:[]}));}catch{}},
    cacheDraft(snapshot){const key='video-workspace-draft:'+this.workspaceId,value='{"revision":'+this.projectRevision+',"state":'+(snapshot||JSON.stringify(this.projectSnapshot()))+'}';try{localStorage.setItem(key,value)}catch{try{localStorage.removeItem(key);sessionStorage.setItem(key,value)}catch{this.saveError='浏览器缓存空间不足；请等项目保存完成后再刷新。'}}},
    persist(){if(!this.projectReady)return persist.call(this);this.cacheProjectView();if(!this._hydrating){const snapshot=JSON.stringify(this.projectSnapshot());if(snapshot===this._ack&&!this._pendingRequest)return true;if(snapshot===this._draftSnapshot)return true;this._draftSnapshot=snapshot;this.cacheDraft(snapshot);if(!this.projectConflict){this.projectStatus='等待保存';clearTimeout(this._projectTimer);this._projectTimer=setTimeout(()=>void this.flushProject().catch(()=>{}),600)}}return true},
    async projectApi(path='',body){const response=await fetch('/api/workspaces/'+this.workspaceId+path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json','X-Workspace-Token':window.WORKSPACE_TOKEN||''},body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(15000),cache:'no-store'});
      const data=await response.json();if(!response.ok){const error=new Error(data.detail||'项目保存失败');error.status=response.status;throw error}return data},
    cacheProjectPreview(){try{const value=JSON.stringify({workspace:this.workspaceId,at:Date.now(),state:this.projectSnapshot()});if(value.length<512000&&!value.includes('data:image/'))sessionStorage.setItem('studio-preview:'+this.workspaceId,value);}catch{}},
    readProjectPreview(){try{const raw=sessionStorage.getItem('studio-preview:'+this.workspaceId);if(!raw||raw.length>512000)return;const value=JSON.parse(raw);if(value.workspace!==this.workspaceId||!Number.isFinite(value.at)||Date.now()-value.at>300000||value.at>Date.now()||!value.state)return;for(const key of ['assets','shots','sequence','saved','messages','notes'])if(!Array.isArray(value.state[key]))return;for(const key of fields)if(value.state[key]!==undefined)this[key]=value.state[key];this.projectPreview=true;}catch{}},
    async loadSharedProject(){if(projectRead)return projectRead;projectRead=(async()=>{this.projectLoading=true;this.projectError='';
      try{const pending=localStorage.getItem('video-workspace-save:'+this.workspaceId)||sessionStorage.getItem('video-workspace-save:'+this.workspaceId);
        const cached=localStorage.getItem('video-workspace-draft:'+this.workspaceId)||sessionStorage.getItem('video-workspace-draft:'+this.workspaceId),draft=cached?JSON.parse(cached):null;
        if(pending){this._pendingRequest=JSON.parse(pending);this.projectRevision=this._pendingRequest.revision;const state=draft?.state||this._pendingRequest.state;for(const key of fields)if(state[key]!==undefined)this[key]=state[key];this.projectReady=true;await this.flushProject();this.projectPreview=false;return}
        const record=await this.projectApi();this._hydrating=true;
        if(record){for(const key of fields)if(record.state[key]!==undefined)this[key]=record.state[key];this.projectRevision=record.revision;this.projectEvents=record.events;
          this._ack=JSON.stringify(this.projectSnapshot());this._draftSnapshot='';this.projectStatus='项目已保存';this.cacheProjectView()}
        if(!record)throw Error('项目不存在，请从创作项目打开画布或从 Chat 建立项目');this.projectReady=true;this.projectPreview=false;this._hydrating=false;
        if(draft){if(JSON.stringify(draft.state)===this._ack){localStorage.removeItem('video-workspace-draft:'+this.workspaceId);sessionStorage.removeItem('video-workspace-draft:'+this.workspaceId)}else{for(const key of fields)if(draft.state[key]!==undefined)this[key]=draft.state[key];this.projectRevision=draft.revision;await this.flushProject()}}
      this.cacheProjectPreview();
      }catch(error){this.projectError=error.message;this.projectStatus=this.projectReady?'刷新未完成':'项目读取失败'}finally{this._hydrating=false;this.projectLoading=false}})();try{await projectRead}finally{projectRead=null}
    },
    async flushProject(){if(this._saving){await this._saving;return this.flushProject()}
      if(!this.projectReady)return;
      if(this.projectConflict){const error=new Error(this.projectError||'项目版本已更新，请先恢复');error.status=409;throw error;}
      const state=this.projectSnapshot();if(JSON.stringify(state)===this._ack&&!this._pendingRequest){this.projectStatus='项目已保存';return;}
      this._pendingRequest=this._pendingRequest||{request_id:crypto.randomUUID(),revision:this.projectRevision,state};
      this.cacheProjectView();try{localStorage.setItem('video-workspace-save:'+this.workspaceId,JSON.stringify(this._pendingRequest));}catch{try{sessionStorage.setItem('video-workspace-save:'+this.workspaceId,JSON.stringify(this._pendingRequest));}catch{this.saveError='浏览器缓存空间不足；正在直接保存到项目，请保存完成前保留此页。';}}
      this.projectStatus='正在保存';
      this._saving=(async()=>{try{const record=await this.projectApi('',this._pendingRequest);for(const asset of record.state.assets){const sent=this._pendingRequest.state.assets.find(a=>a.id===asset.id),live=this.assets.find(a=>a.id===asset.id);if(sent&&live&&live.file===sent.file&&sent.file?.startsWith('data:image/')&&asset.file!==sent.file)live.file=asset.file;}this.projectRevision=record.revision;this.projectEvents=record.events;this._ack=JSON.stringify(record.state);this._pendingRequest=null;if(JSON.stringify(this.projectSnapshot())!==this._ack)this.cacheDraft();localStorage.removeItem('video-workspace-save:'+this.workspaceId);sessionStorage.removeItem('video-workspace-save:'+this.workspaceId);this.saveError='';this.projectError='';this.projectConflict=false;this.projectStatus='项目已保存';this.cacheProjectPreview()}
        catch(error){this.projectError=error.message;this.projectConflict=error.status===409;this.projectStatus='保存未完成';throw error}})();
      try{await this._saving}finally{this._saving=null}
      if(JSON.stringify(this.projectSnapshot())!==this._ack)return this.flushProject();
      localStorage.removeItem('video-workspace-draft:'+this.workspaceId);sessionStorage.removeItem('video-workspace-draft:'+this.workspaceId);
    },
    async showProject(){this.panel='project';void this.readProjectBackup().then(backup=>{this.projectBackupAvailable=!!backup;this.projectBackupTime=backup?JSON.parse(backup).saved_at:0;}).catch(()=>{});try{await this.flushProject();this.projectTasks=await this.projectApi('/tasks')}catch(error){this.projectError=error.message}},
    async storeProjectBackup(backup){const key='video-workspace-backup:'+this.workspaceId;
      try{localStorage.setItem(key,backup);}catch{try{sessionStorage.setItem(key,backup);}catch{try{await studioBackupDatabase(this.workspaceId,backup);}catch{throw Error('当前编辑仍保留，但浏览器无法完成备份；请保留此页并重试。');}}}this.projectBackupAvailable=true;},
    async readProjectBackup(){const key='video-workspace-backup:'+this.workspaceId,backups=[];for(const storage of [localStorage,sessionStorage]){try{const value=storage.getItem(key);if(value)backups.push(value);}catch{}}
      const database=await studioBackupDatabase(this.workspaceId).catch(()=>null);if(database)backups.push(database);
      return backups.flatMap(value=>{try{const row=JSON.parse(value);return row.workspace===this.workspaceId&&row.state&&Number.isFinite(row.saved_at)?[{value,time:row.saved_at}]:[];}catch{return [];}}).sort((a,b)=>b.time-a.time)[0]?.value;},
    downloadBackup(backup){const link=document.createElement('a'),url=URL.createObjectURL(new Blob([backup],{type:'application/json'}));link.href=url;link.download='创作项目-恢复备份.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);},
    async downloadProjectBackup(){try{const backup=await this.readProjectBackup();if(!backup)throw Error('暂无未保存编辑的备份');this.downloadBackup(backup);}catch(error){this.projectError=error.message;}},
    async preserveAndReadLatest(){try{const latest=await this.projectApi();if(!latest)throw Error('服务端项目暂不可读');
      const backup=JSON.stringify({workspace:this.workspaceId,saved_at:Date.now(),state:this.projectSnapshot(),request:this._pendingRequest},null,2);
      await this.storeProjectBackup(backup);this.downloadBackup(backup);
      localStorage.removeItem('video-workspace-save:'+this.workspaceId);sessionStorage.removeItem('video-workspace-save:'+this.workspaceId);localStorage.removeItem('video-workspace-draft:'+this.workspaceId);sessionStorage.removeItem('video-workspace-draft:'+this.workspaceId);this._pendingRequest=null;this.projectConflict=false;await this.loadSharedProject();
      if(!this.projectError&&this.pendingChatHref){this.panel='';await this.continueToChat();}
    }catch(error){this.projectError=error.message}},
    async refreshTasks(){try{this.projectTasks=await this.projectApi('/tasks')}catch(error){this.projectError=error.message}},
    get taskJobs(){return this.projectTasks.flatMap(task=>task.jobs.map(job=>({...job,object:task.object,name:this.assets.find(a=>a.id===task.object)?.name||task.name})))},
    projectStateLabel(state){return {queued:'排队中',running:'正在修图',succeeded:'已有结果',failed:'执行失败',cancelled:'已取消'}[state]||state},
    saveClip(){saveClip.call(this);if(!this.panel){const shot=this.shots.find(s=>s.id===this.active);if(shot){shot.inputReview=false;this.persist()}}},
    nextClipAction(shot){return shot.inputReview?'检查画面要求 →':!(shot.mode==='first'?shot.first:shot.refs.length)?'选画面 →':!shot.prompt.trim()?'写视频要求 →':'查看生成方案 →'},
    nextClip(shot){if(shot.inputReview||!(shot.mode==='first'?shot.first:shot.refs.length)||!shot.prompt.trim())this.openClip(shot.id);else this.prepare(shot.id)},
    keydown(e){if(this.fullEditor)return;keydown.call(this,e)},
    async openEdit(){const asset=this.asset;if(!asset||asset.pending)return;
      this.editSource=JSON.parse(JSON.stringify(asset));this.editAssetId=asset.id;
      this.editorToken=crypto.randomUUID();const ticket=this.editorToken;
      this.editorUrl='';this.editorProject='';this.editorCandidate=null;this.editorFailure='';this.editorLoading=true;this.editorReady=false;this.fullEditor=true;
      try{await this.flushProject();const meta=await this.editApi('/full/open',{workspace:this.workspaceId,object_id:asset.id,file:asset.file,name:asset.name});
        if(!this.fullEditor||this.editorToken!==ticket)return;
        this.editorProject=meta.project;
        this.editorUrl='/editor/precision-workspace.html?project='+meta.project+'&nonce='+ticket+'&workspace='+this.workspaceId+'&model='+encodeURIComponent(asset.imageModel||'');
        this._editorTimer=setTimeout(()=>{if(this.fullEditor&&this.editorToken===ticket&&!this.editorReady){this.editorFailure='精修工作区没有加载完成。你的图片仍保留，可以返回画布重试。';this.editorLoading=false}},15000);
      }catch(error){if(this.editorToken===ticket){this.editorFailure=error.message;this.editorLoading=false}}
    },
    closeFullEditor(){if(this.editorApplying)return;clearTimeout(this._editorTimer);this.fullEditor=false;this.editorToken='';this.editorUrl='';this.editorCandidate=null;
      this.$nextTick(()=>this.focusObject(this.editAssetId))},
    async reviewFullEditor(revision){if(this.editorApplying)return;this.editorApplying=true;this.editorFailure='';
      const ticket=this.editorToken;
      try{const candidate=await this.editApi('/full/'+this.editorProject+'/preview',{revision});
        if(this.fullEditor&&this.editorToken===ticket){this.editorCandidate=candidate;this.$nextTick(()=>document.querySelector('.full-edit-review button')?.focus())}
      }catch(error){this.editorFailure=error.message}finally{this.editorApplying=false}
    },
    get affectedClips(){return this.shots.filter(s=>s.mode==='first'?s.first===this.editAssetId:s.refs.includes(this.editAssetId))},
    async adoptFullEditor(){if(!this.editorCandidate||this.editorApplying)return;
      const asset=this.assets.find(a=>a.id===this.editAssetId);
      if(!asset||![this.editSource.file,this.editorCandidate.output].includes(asset.file)){this.editorFailure='画布中的原图已改变，未覆盖。请返回画布重新核对。';return}
      this.editorApplying=true;this.editorFailure='';
      try{
        const response=await fetch('/api/miniclaw/canvas/projects/'+this.editorProject,{headers:{'X-Workspace-Token':window.WORKSPACE_TOKEN},cache:'no-store'});
        const latest=await response.json();if(!response.ok)throw Error(latest.detail||'读取精修进度失败');
        if(latest.revision!==this.editorCandidate.revision)throw Error('精修画面又有变化，请返回精修重新比较。');
        if(![this.editSource.file,this.editorCandidate.output].includes(asset.file))throw Error('画布素材刚刚发生变化，请重新核对。');
        if(asset.file!==this.editorCandidate.output){this.remember();asset.originalFile=asset.originalFile||asset.file;asset.file=this.editorCandidate.output;asset.editProject=this.editorProject;
          if(this.editorCandidate.width&&this.editorCandidate.height)asset.h=Math.min(600,Math.max(120,asset.w*this.editorCandidate.height/this.editorCandidate.width));}
        const affected=this.affectedClips;for(const shot of affected){shot.dirty=true;shot.inputReview=true}
        this.saved=this.saved.filter(s=>!affected.some(a=>a.id===s.id));
        this.edits[asset.id]={...(this.edits[asset.id]||{}),applied:true,project:this.editorProject,revision:this.editorCandidate.revision};
        if(!this.persist())throw Error(this.saveError);await this.flushProject();
        this.editorApplying=false;this.closeFullEditor();this.notify(affected.length?'图片已更新 · '+affected.length+' 个片段待检查':'图片已更新');
      }catch(error){this.editorFailure=error.message}finally{this.editorApplying=false}
    }
  }));
  return app;
}
