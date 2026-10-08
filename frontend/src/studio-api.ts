import {readApi,writeApi} from './management-api';
export async function saveStudioIdea(workspace:string,owner:string,item:string) {
  if(!/^row-\d+$/.test(item))throw Error('请等待回复保存后重试');
  const record=await readApi<{revision:number}>(`/api/workspaces/${workspace}`);
  return await writeApi<{events:{object?:string}[]}>(`/api/workspaces/${workspace}/commands`,'POST',{request_id:crypto.randomUUID(),revision:record.revision,action:'idea',args:{owner,message:Number(item.slice(4))}});
}
