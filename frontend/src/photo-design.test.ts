import { expect, test } from 'vitest';
import { photoLayout } from './photo-design';
import { nextCreation } from './creator-guide';
import type { CanvasAsset } from './canvas-api';
import type { CreatorProject } from './creator-api';

test('wide and tall photos remain entirely inside the design with their aspect ratio intact', () => {
  for (const [width, height] of [[1260,968], [500,2000]]) {
    const asset = { id: 'a'.repeat(32), width, height } as CanvasAsset;
    for (const preset of ['paper','dark'] as const) {
      const document = photoLayout(asset, preset, '乳白 · 圆弧', '细看轮廓与配色');
      const layer = document.layers.find(l => l.kind === 'image')!;
      expect(layer.asset_id).toBe(asset.id);
      expect(layer.scale_x).toBe(layer.scale_y);
      expect(layer.x).toBeGreaterThanOrEqual(56 - 1e-6);
      expect(layer.y).toBeGreaterThanOrEqual(292);
      expect(layer.x + width * layer.scale_x).toBeLessThanOrEqual(1024 + 1e-6);
      expect(layer.y + height * layer.scale_y).toBeLessThanOrEqual(1092 + 1e-6);
      expect(asset).toEqual({id: 'a'.repeat(32), width, height});
    }
  }
});
test('overlong text is rejected before creating a misleading clipped preview', () => {
  expect(() => photoLayout({width: 10,height: 10} as CanvasAsset, 'paper', '字'.repeat(17), '')).toThrow();
});
test('guidance stops at missing input or stale adopted results rather than proposing video', () => {
  const p = { assets:{}, facts:'', script:'', flow:{brief:'empty',cover:'empty',script:'empty'} } as unknown as CreatorProject;
  expect(nextCreation(p).action).toBe('上传商品原图');
  p.assets.source = { id: 'source', name: 'source.png', bytes: 1 };
  expect(nextCreation(p).stage).toBe('facts');
  p.facts = '已核对外观';
  expect(nextCreation(p).stage).toBe('cover');
  p.assets.cover = { id: 'cover', name: 'cover.png', bytes: 1 };
  p.flow!.cover = 'adopted';
  expect(nextCreation(p).stage).toBe('script');
  p.script = '自然介绍'; p.flow!.script = 'adopted';
  expect(nextCreation(p).title).toContain('放在一起');
  p.flow!.cover = 'review';
  expect(nextCreation(p).stage).toBe('cover');
});
