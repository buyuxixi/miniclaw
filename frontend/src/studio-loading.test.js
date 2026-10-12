import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {test,expect} from 'vitest';
function production(base){
 return runInNewContext(readFileSync(new URL('../public/studio/production.js',import.meta.url),'utf8')+';withStudioProduction(base)',{base,URLSearchParams,location:{search:''},setInterval,clearInterval,Promise});
}
test('failed workspace read always exits the outer loading state',async()=>{
 const app=production({async loadSharedProject(){this.projectError='offline';this.projectReady=false;}});
 await app.loadSharedProject();expect(app.productionLoading).toBe(false);expect(app.projectError).toBe('offline');
});
test('slow metadata and videos do not gate the canvas or require the audit endpoint',async()=>{
 let done,started;const stalled=new Promise(r=>done=r),requested=new Promise(r=>started=r);let nextTick=0;
 const app=production({async loadSharedProject(){this.projectReady=true;},history:[],_initialFocus:true,$nextTick(){nextTick++;}});
 const calls=[];app.projectApi=path=>{calls.push(path);started();return stalled;};app.refreshVideo=()=>stalled;app.refreshAudit=()=>{throw Error('audit must load on demand');};
 const load=app.loadSharedProject();await requested;expect(app.productionLoading).toBe(false);expect(app.projectReady).toBe(true);expect(calls).toEqual(['/info']);done({name:'fresh'});
 // Name formatter is an existing dependency of the studio, not under test here.
 await load;expect(app.productionLoading).toBe(false);
});
