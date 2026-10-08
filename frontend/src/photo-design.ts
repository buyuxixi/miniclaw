import { makeLayer, type CanvasAsset, type CanvasDocument } from './canvas-api';
export type PhotoPreset = 'paper' | 'dark';
export interface CanvasDesignRequest { mode: 'layout' | 'photo'; preset?: PhotoPreset; brief?: string }
export const photoPresets = [
  { id: 'paper', name: '留白画册', color: '#f2efe7', ink: '#30392f', note: '暖白底色、完整商品、克制的文字与留白。' },
  { id: 'dark', name: '暗调展陈', color: '#19211e', ink: '#e2d5b8', note: '深色底面、细线分隔，突出器物与颜色。' },
] as const;

// The photograph is contained, never stretched or cropped. Native layers remain editable.
export function photoLayout(asset: CanvasAsset, preset: PhotoPreset, title: string, subtitle: string): CanvasDocument {
  if (!asset.width || !asset.height || title.length > 16 || subtitle.length > 28) throw new Error('标题最多16字，说明最多28字；图片尺寸必须有效。');
  const palette = photoPresets.find(p => p.id === preset)!;
  const scale = Math.min(968 / asset.width, 800 / asset.height);
  const width = asset.width * scale, height = asset.height * scale;
  const layers = [
    makeLayer('text', '栏目', 968, 42, { x: 56, y: 60, text: 'V I S U A L   N O T E S', font_size: 22, fill: palette.ink }),
    makeLayer('shape', '分隔线', 968, 2, { x: 56, y: 122, shape: 'rectangle', fill: palette.ink, opacity: .3 }),
    makeLayer('text', '标题', 968, 86, { x: 56, y: 164, text: title, font_size: 54, fill: palette.ink }),
    makeLayer('image', '原画面 · 完整保留', asset.width, asset.height, { x: (1080 - width) / 2, y: 292 + (800 - height) / 2, asset_id: asset.id, scale_x: scale, scale_y: scale }),
    makeLayer('shape', '页脚线', 968, 2, { x: 56, y: 1150, shape: 'rectangle', fill: palette.ink, opacity: .3 }),
    makeLayer('text', '说明', 968, 60, { x: 56, y: 1192, text: subtitle, font_size: 30, fill: palette.ink }),
    makeLayer('text', '页码', 968, 35, { x: 56, y: 1280, text: '01   /   IMAGE STUDY', font_size: 18, fill: palette.ink, opacity: .65 }),
  ];
  return { schema_version: 1, width: 1080, height: 1350, background: palette.color, layers };
}

export const photographyPrompt = `将这张实际商品照片打磨为克制的编辑摄影：保留同一个商品的轮廓、颜色、比例、部件位置、绳线、标识和原有纹理，主体完整。用柔和侧光、自然渐变暗背景和真实的接触阴影，让商品与背景分离；控制刺眼高光但保留表面真实反光，不磨平纹理，不做塑料感。画面简洁，不添加文字、品牌、道具或第二件商品。若有托举商品的手，保留其自然结构。只优化摄影呈现，不假造材质、工艺或功能。`;
