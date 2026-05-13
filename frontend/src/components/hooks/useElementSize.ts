import { useEffect, useRef, useState } from "react";
import type { DependencyList, RefObject } from "react";
import type { ElementSize } from "../export/exportSizing";

export function useElementSize<T extends HTMLElement>(dependencies: DependencyList = []): readonly [RefObject<T | null>, ElementSize] {
  const ref = useRef<T | null>(null);
  const [size, setSize] = useState<ElementSize>({ width: 0, height: 0 });

  useEffect(() => {
    const element = ref.current;
    if (!element) return undefined;
    const updateSize = () => {
      const rect = element.getBoundingClientRect();
      setSize({ width: rect.width, height: rect.height });
    };
    updateSize();
    const observer = new ResizeObserver(updateSize);
    observer.observe(element);
    return () => observer.disconnect();
  }, dependencies);

  return [ref, size] as const;
}
