import { useEffect, useRef, useState } from "react";
import {
  Stage,
  Layer,
  Group,
  Rect,
  Ellipse,
  Image as KImage,
  Text,
  Transformer,
  Line,
} from "react-konva";
import type Konva from "konva";
import { useImageBlob } from "./image-api";
import {
  type CanvasAsset,
  type CanvasDocument,
  type CanvasLayer,
  type Selection,
  projectOwner,
} from "./canvas-api";

export type CanvasTool =
  | "move"
  | "pan"
  | "rectangle"
  | "lasso"
  | "brush"
  | "sam"
  | "crop";
export interface View {
  x: number;
  y: number;
  scale: number;
}
export function useLoadedImage(url: string) {
  const [image, setImage] = useState<HTMLImageElement>();
  useEffect(() => {
    setImage(undefined);
    if (!url) return;
    const img = new window.Image();
    let alive = true;
    img.onload = () => {
      if (alive) setImage(img);
    };
    img.src = url;
    return () => {
      alive = false;
      img.onload = null;
    };
  }, [url]);
  return image;
}
function ImageNode({
  project,
  asset,
  ...props
}: { project: string; asset?: CanvasAsset } & Omit<
  Konva.ImageConfig,
  "image"
>) {
  const { url } = useImageBlob(projectOwner(project), asset);
  const image = useLoadedImage(url);
  return <KImage {...props} image={image} />;
}
function SelectionNode({
  selection,
  layer,
}: {
  selection: Selection;
  layer: CanvasLayer;
}) {
  const [url, setUrl] = useState("");
  useEffect(() => {
    let alive = true;
    const image = new window.Image();
    image.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = image.width;
      canvas.height = image.height;
      const context = canvas.getContext("2d")!;
      context.drawImage(image, 0, 0);
      const data = context.getImageData(0, 0, image.width, image.height);
      for (let i = 0; i < data.data.length; i += 4) {
        const alpha = data.data[i];
        data.data[i] = 81;
        data.data[i + 1] = 125;
        data.data[i + 2] = 255;
        data.data[i + 3] = Math.round(alpha * 0.38);
      }
      context.putImageData(data, 0, 0);
      if (alive) setUrl(canvas.toDataURL());
    };
    image.src = `data:image/png;base64,${selection.mask}`;
    return () => {
      alive = false;
    };
  }, [selection.mask]);
  const image = useLoadedImage(url);
  return (
    <KImage
      image={image}
      x={layer.x}
      y={layer.y}
      width={layer.width}
      height={layer.height}
      scaleX={layer.scale_x}
      scaleY={layer.scale_y}
      rotation={layer.rotation}
      listening={false}
    />
  );
}

export function CanvasStage({
  project,
  document: doc,
  assets,
  selection,
  selected,
  tool,
  busy,
  view,
  setView,
  onSelect,
  onChange,
  onPath,
  onCrop,
  size,
}: {
  project: string;
  document: CanvasDocument;
  assets: CanvasAsset[];
  selection: Selection | null;
  selected: string;
  tool: CanvasTool;
  busy: boolean;
  view: View;
  setView: (view: View) => void;
  onSelect: (id: string) => void;
  onChange: (id: string, patch: Partial<CanvasLayer>) => void;
  onPath: (points: number[][]) => void;
  onCrop: (points: number[][]) => void;
  size: { width: number; height: number };
}) {
  const stage = useRef<Konva.Stage>(null);
  const transformer = useRef<Konva.Transformer>(null);
  const [path, setPath] = useState<number[][]>([]);
  const pathRef = useRef<number[][]>([]);
  const drawing = useRef(false);
  const target = doc.layers.find((l) => l.id === selected);
  useEffect(() => {
    const node = stage.current?.findOne(`#layer-${selected}`);
    transformer.current?.nodes(
      tool === "move" && target && !target.locked && target.visible && node
        ? [node]
        : [],
    );
  }, [selected, target, tool, busy]);
  function point() {
    const p = stage.current?.getPointerPosition();
    return p
      ? [(p.x - view.x) / view.scale, (p.y - view.y) / view.scale]
      : [0, 0];
  }
  function start() {
    if (busy || tool === "move" || tool === "pan") return;
    const p = point();
    if (tool === "sam") {
      onPath([p]);
      return;
    }
    drawing.current = true;
    pathRef.current = [p];
    setPath([p]);
  }
  function motion() {
    if (!drawing.current) return;
    const p = point();
    const before = pathRef.current.at(-1)!;
    if (Math.hypot(p[0] - before[0], p[1] - before[1]) < 2) return;
    pathRef.current =
      tool === "rectangle" || tool === "crop"
        ? [pathRef.current[0], p]
        : [...pathRef.current.slice(-2046), p];
    setPath(pathRef.current);
  }
  function finish() {
    if (!drawing.current) return;
    drawing.current = false;
    const points = pathRef.current;
    if (points.length > 1) {
      if (tool === "crop") onCrop(points);
      else onPath(points);
    }
    pathRef.current = [];
    setPath([]);
  }
  const points = path.flat();
  const corners =
    path.length > 1
      ? {
          x: Math.min(path[0][0], path.at(-1)![0]),
          y: Math.min(path[0][1], path.at(-1)![1]),
          width: Math.abs(path[0][0] - path.at(-1)![0]),
          height: Math.abs(path[0][1] - path.at(-1)![1]),
        }
      : undefined;
  return (
    <Stage
      ref={stage}
      width={size.width}
      height={size.height}
      onMouseDown={start}
      onTouchStart={start}
      onMouseMove={motion}
      onTouchMove={motion}
      onMouseUp={finish}
      onTouchEnd={finish}
      onWheel={(event) => {
        event.evt.preventDefault();
        const p = stage.current?.getPointerPosition();
        if (!p) return;
        const scale = Math.max(
          0.04,
          Math.min(8, view.scale * (event.evt.deltaY > 0 ? 0.9 : 1.1)),
        );
        const px = (p.x - view.x) / view.scale,
          py = (p.y - view.y) / view.scale;
        setView({ scale, x: p.x - px * scale, y: p.y - py * scale });
      }}
    >
      <Layer>
        <Group
          x={view.x}
          y={view.y}
          scaleX={view.scale}
          scaleY={view.scale}
          draggable={tool === "pan" && !busy}
          onDragEnd={(e) => {
            if (e.target === e.currentTarget)
              setView({ ...view, x: e.target.x(), y: e.target.y() });
          }}
        >
          <Rect
            width={doc.width}
            height={doc.height}
            fill="#fff"
            shadowColor="#000"
            shadowBlur={30}
            shadowOpacity={0.12}
            listening={false}
          />
          <Group clipWidth={doc.width} clipHeight={doc.height}>
            <Rect
              width={doc.width}
              height={doc.height}
              fill={doc.background}
              listening={false}
            />
            {doc.layers
              .filter((layer) => layer.visible)
              .map((layer) => {
                const props = {
                  id: `layer-${layer.id}`,
                  x: layer.x,
                  y: layer.y,
                  width: layer.width,
                  height: layer.height,
                  scaleX: layer.scale_x,
                  scaleY: layer.scale_y,
                  rotation: layer.rotation,
                  opacity: layer.opacity,
                  draggable: tool === "move" && !layer.locked && !busy,
                  onClick: () => {
                    if (tool === "move") onSelect(layer.id);
                  },
                  onTap: () => {
                    if (tool === "move") onSelect(layer.id);
                  },
                  onDragEnd: (e: Konva.KonvaEventObject<DragEvent>) => {
                    e.cancelBubble = true;
                    onChange(layer.id, { x: e.target.x(), y: e.target.y() });
                  },
                  onTransformEnd: (e: Konva.KonvaEventObject<Event>) => {
                    const node = e.target;
                    onChange(layer.id, {
                      x: node.x(),
                      y: node.y(),
                      scale_x: Math.max(0.02, node.scaleX()),
                      scale_y: Math.max(0.02, node.scaleY()),
                      rotation: node.rotation(),
                    });
                  },
                };
                if (layer.kind === "image")
                  return (
                    <ImageNode
                      key={layer.id}
                      project={project}
                      asset={assets.find((a) => a.id === layer.asset_id)}
                      {...props}
                    />
                  );
                if (layer.kind === "text")
                  return (
                    <Text
                      key={layer.id}
                      {...props}
                      text={layer.text}
                      fontSize={layer.font_size}
                      fill={layer.fill}
                      fontFamily="Microsoft YaHei, sans-serif"
                      wrap="none"
                      lineHeight={1.35}
                    />
                  );
                return layer.shape === "ellipse" ? (
                  <Group key={layer.id} {...props}>
                    <Ellipse
                      x={layer.width / 2}
                      y={layer.height / 2}
                      radiusX={layer.width / 2}
                      radiusY={layer.height / 2}
                      fill={layer.fill}
                    />
                  </Group>
                ) : (
                  <Rect key={layer.id} {...props} fill={layer.fill} />
                );
              })}
            {selection && target?.id === selection.layer_id && (
              <SelectionNode selection={selection} layer={target} />
            )}
          </Group>
          <Transformer
            ref={transformer}
            flipEnabled={false}
            rotateEnabled={!busy}
            enabledAnchors={busy ? [] : undefined}
            boundBoxFunc={(oldBox, newBox) =>
              newBox.width < 2 || newBox.height < 2 ? oldBox : newBox
            }
          />
          {corners && (tool === "rectangle" || tool === "crop") ? (
            <Rect
              {...corners}
              fill="#517dff30"
              stroke="#517dff"
              strokeWidth={1 / view.scale}
              dash={[5 / view.scale, 3 / view.scale]}
              listening={false}
            />
          ) : (
            path.length > 0 && (
              <Line
                points={points}
                stroke="#517dff"
                strokeWidth={3 / view.scale}
                closed={tool === "lasso"}
                fill={tool === "lasso" ? "#517dff30" : undefined}
                listening={false}
              />
            )
          )}
        </Group>
      </Layer>
    </Stage>
  );
}
