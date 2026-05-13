export const DEFAULT_EXPORT_PERCENTAGE = 100;

export type ElementSize = {
  width: number;
  height: number;
};

export function computeArtboardSize(canvasSize: ElementSize, outputWidth: number, outputHeight: number) {
  const exportAspect = outputWidth / outputHeight;
  const canvasAspect = canvasSize.width > 0 && canvasSize.height > 0 ? canvasSize.width / canvasSize.height : exportAspect;
  if (canvasSize.width <= 0 || canvasSize.height <= 0) return null;
  if (exportAspect >= canvasAspect) {
    return {
      width: canvasSize.width,
      height: canvasSize.width / exportAspect,
    };
  }
  return {
    width: canvasSize.height * exportAspect,
    height: canvasSize.height,
  };
}

export function clampNumber(value: number, min: number, max: number) {
  if (!Number.isFinite(value)) return min;
  return Math.max(min, Math.min(max, value));
}
