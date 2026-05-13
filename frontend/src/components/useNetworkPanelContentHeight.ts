import { useLayoutEffect, useState } from "react";
import type { RefObject } from "react";

export function useNetworkPanelContentHeight(panelRef: RefObject<HTMLElement | null>) {
  const [height, setHeight] = useState<number | null>(null);

  useLayoutEffect(() => {
    const panel = panelRef.current;
    if (!panel) return;

    const updateHeight = () => {
      setHeight(Math.ceil(measureNetworkPanelContentHeight(panel)));
    };

    updateHeight();

    const observer = new ResizeObserver(updateHeight);
    observer.observe(panel);
    for (const element of measuredPanelChildren(panel)) observer.observe(element);
    window.addEventListener("resize", updateHeight);

    return () => {
      observer.disconnect();
      window.removeEventListener("resize", updateHeight);
    };
  }, [panelRef]);

  return height;
}

function measureNetworkPanelContentHeight(panel: HTMLElement) {
  const header = panel.querySelector<HTMLElement>(".network-panel__header");
  const svgWrap = panel.querySelector<HTMLElement>(".network-svg-wrap");
  const svg = panel.querySelector<SVGSVGElement>(".network-svg");
  if (!header || !svgWrap || !svg) return panel.getBoundingClientRect().height;

  const panelStyle = window.getComputedStyle(panel);
  const wrapStyle = window.getComputedStyle(svgWrap);
  return (
    borderBlockSize(panelStyle) +
    header.getBoundingClientRect().height +
    paddingBlockSize(wrapStyle) +
    svg.getBoundingClientRect().height
  );
}

function measuredPanelChildren(panel: HTMLElement) {
  return [
    panel.querySelector<HTMLElement>(".network-panel__header"),
    panel.querySelector<HTMLElement>(".network-svg-wrap"),
    panel.querySelector<SVGSVGElement>(".network-svg"),
  ].filter((element): element is HTMLElement | SVGSVGElement => element !== null);
}

function borderBlockSize(style: CSSStyleDeclaration) {
  return cssPixels(style.borderTopWidth) + cssPixels(style.borderBottomWidth);
}

function paddingBlockSize(style: CSSStyleDeclaration) {
  return cssPixels(style.paddingTop) + cssPixels(style.paddingBottom);
}

function cssPixels(value: string) {
  return Number.parseFloat(value) || 0;
}
