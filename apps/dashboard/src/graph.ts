import { NODES } from "./mapping";
import type { NodeId, NodeSubtitles } from "./types";

const SVG_NS = "http://www.w3.org/2000/svg";
const VIEW_W = 1240;
const VIEW_H = 400;
const NODE_W = 150;
const NODE_H = 88;
const NODE_Y = 56;
const MARGIN_X = 10;
const STEP = (VIEW_W - 2 * MARGIN_X - NODE_W) / (NODES.length - 1);
const EDGE_Y = NODE_Y + NODE_H / 2;

export interface Graph {
  setActive(node: NodeId, warn: boolean): void;
  setNodeSubtitles(subtitles: NodeSubtitles): void;
  flashFeedback(): void;
  reset(): void;
}

function el<K extends keyof SVGElementTagNameMap>(
  tag: K,
  attrs: Record<string, string>,
): SVGElementTagNameMap[K] {
  const item = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) item.setAttribute(key, value);
  return item;
}

function nodeX(index: number): number {
  return MARGIN_X + index * STEP;
}

export function createGraph(container: HTMLElement): Graph {
  const svg = el("svg", { viewBox: `0 0 ${VIEW_W} ${VIEW_H}`, preserveAspectRatio: "xMidYMid meet" });
  const defs = el("defs", {});
  for (const [id, className] of [["arrow-idle", "arrow-idle"], ["arrow-done", "arrow-done"], ["arrow-feedback", "arrow-feedback"]]) {
    const marker = el("marker", { id, viewBox: "0 0 10 10", refX: "9", refY: "5", markerWidth: "7", markerHeight: "7", orient: "auto-start-reverse" });
    marker.appendChild(el("path", { d: "M 0 0 L 10 5 L 0 10 z", class: className }));
    defs.appendChild(marker);
  }
  svg.appendChild(defs);

  const edges: SVGLineElement[] = [];
  for (let index = 0; index < NODES.length - 1; index += 1) {
    const edge = el("line", {
      x1: String(nodeX(index) + NODE_W + 2), y1: String(EDGE_Y),
      x2: String(nodeX(index + 1) - 8), y2: String(EDGE_Y),
      class: "edge", "marker-end": "url(#arrow-idle)",
    });
    edges.push(edge);
    svg.appendChild(edge);
  }

  const fromX = nodeX(NODES.length - 1) + NODE_W / 2;
  const toX = nodeX(2) + NODE_W / 2;
  const bottomY = NODE_Y + NODE_H;
  const feedback = el("path", {
    d: `M ${fromX} ${bottomY + 4} C ${fromX} ${VIEW_H - 60}, ${toX} ${VIEW_H - 60}, ${toX} ${bottomY + 12}`,
    class: "feedback", "marker-end": "url(#arrow-feedback)",
  });
  svg.appendChild(feedback);

  const feedbackLabel = el("text", { x: String((fromX + toX) / 2), y: String(VIEW_H - 72), class: "feedback-label", "text-anchor": "middle" });
  feedbackLabel.textContent = "feedback: price · stock · failure";
  svg.appendChild(feedbackLabel);

  const groups = new Map<NodeId, SVGGElement>();
  const subtitles = new Map<NodeId, SVGTextElement>();
  NODES.forEach((spec, index) => {
    const x = nodeX(index);
    const group = el("g", { class: "node", "data-state": "idle" });
    group.appendChild(el("rect", { x: String(x), y: String(NODE_Y), width: String(NODE_W), height: String(NODE_H), rx: "12", class: "box" }));
    const number = el("text", { x: String(x + 14), y: String(NODE_Y + 22), class: "num" });
    number.textContent = String(spec.num);
    group.appendChild(number);
    const name = el("text", { x: String(x + NODE_W / 2), y: String(NODE_Y + 44), class: "name", "text-anchor": "middle" });
    name.textContent = spec.name;
    group.appendChild(name);
    const sub = el("text", { x: String(x + NODE_W / 2), y: String(NODE_Y + 66), class: "sub", "text-anchor": "middle" });
    sub.textContent = spec.sub;
    group.appendChild(sub);
    groups.set(spec.id, group);
    subtitles.set(spec.id, sub);
    svg.appendChild(group);
  });

  container.replaceChildren(svg);
  const order: NodeId[] = NODES.map((node) => node.id);
  let feedbackTimer: number | undefined;

  function apply(activeIndex: number, warn: boolean): void {
    order.forEach((id, index) => {
      const group = groups.get(id);
      if (!group) return;
      group.setAttribute("data-state", index < activeIndex ? "done" : index === activeIndex ? "active" : "idle");
      group.classList.toggle("warn", warn && index === activeIndex);
    });
    edges.forEach((edge, index) => {
      const done = index < activeIndex;
      edge.setAttribute("data-state", done ? "done" : "idle");
      edge.setAttribute("marker-end", done ? "url(#arrow-done)" : "url(#arrow-idle)");
    });
  }

  function setNodeSubtitles(values: NodeSubtitles): void {
    for (const spec of NODES) {
      const subtitle = subtitles.get(spec.id);
      if (subtitle) subtitle.textContent = values[spec.id] ?? spec.sub;
    }
  }

  return {
    setActive(node, warn) { apply(order.indexOf(node), warn); },
    setNodeSubtitles,
    flashFeedback() {
      feedback.classList.add("on");
      window.clearTimeout(feedbackTimer);
      feedbackTimer = window.setTimeout(() => feedback.classList.remove("on"), 2600);
    },
    reset() {
      apply(-1, false);
      setNodeSubtitles({});
      feedback.classList.remove("on");
    },
  };
}
