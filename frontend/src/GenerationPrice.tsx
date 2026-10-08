import type { CanvasCapabilities } from './canvas-api';

export function GenerationPrice({cloud,compact=false}:{cloud?:CanvasCapabilities['cloud'];compact?:boolean}){
  if(!cloud)return null;
  const content=<p className="canvas-hint generation-price">{cloud.model} · {cloud.reference_cny_per_image==null?'参考价格待核对':`中国内地参考 ¥${cloud.reference_cny_per_image.toFixed(2)} / 张`}<br/><small>实际扣费待账单核对{cloud.price_source&&<> · <a href={cloud.price_source} target="_blank" rel="noreferrer">官方价格 ↗</a></>}</small></p>;
  return compact?<details className="generation-price-details"><summary>模型与费用</summary>{content}</details>:content;
}
