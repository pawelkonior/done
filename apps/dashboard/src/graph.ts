import { NODES } from "./mapping";
import type { NodeId } from "./types";

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
  /** Move the pulse to `node`; earlier nodes become done, later ones idle. */
  setActive(node: NodeId, warn: boolean): void;
  /** Light the return edge for a moment. */
  flashFeedback(): void;
  reset(): void;
}

function el<K extends keyof SVGElementTagNameMap>(
  tag: K,
  attrs: Record<string, string>,
): SVGElementTagNameMap[K] {
  const element = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) {
    element.setAttribute(key, value);
  }
  return element;
}

function nodeX(index: number): number {
  return MARGIN_X + index * STEP;
}

export function createGraph(container: HTMLElement): Graph {
  const svg = el("svg", {
    viewBox: `0 0 ${VIEW_W} ${VIEW_H}`,
    preserveAspectRatio: "xMidYMid meet",
  });

  const defs = el("defs", {});
  for (const [id, cls] of [
    ["arrow-idle", "arrow-idle"],
    ["arrow-done", "arrow-done"],
    ["arrow-feedback", "arrow-feedback"],
  ]) {
    const marker = el("marker", {
      id,
      viewBox: "0 0 10 10",
      refX: "9",
      refY: "5",
      markerWidth: "7",
      markerHeight: "7",
      orient: "auto-start-reverse",
    });
    const tip = el("path", { d: "M 0 0 L 10 5 L 0 10 z", class: cls });
    marker.appendChild(tip);
    defs.appendChild(marker);
  }
  svg.appendChild(defs);

  // Forward edges between consecutive nodes.
  const edges: SVGLineElement[] = [];
  for (let i = 0; i < NODES.length - 1; i += 1) {
    const line = el("line", {
      x1: String(nodeX(i) + NODE_W + 2),
      y1: String(EDGE_Y),
      x2: String(nodeX(i + 1) - 8),
      y2: String(EDGE_Y),
      class: "edge",
      "marker-end": "url(#arrow-idle)",
    });
    edges.push(line);
    svg.appendChild(line);
  }

  // Feedback edge: from Wynik back to Snapshot, below the row.
  const fromX = nodeX(NODES.length - 1) + NODE_W / 2;
  const toX = nodeX(2) + NODE_W / 2;
  const bottomY = NODE_Y + NODE_H;
  const feedback = el("path", {
    d: `M ${fromX} ${bottomY + 4} C ${fromX} ${VIEW_H - 60}, ${toX} ${VIEW_H - 60}, ${toX} ${bottomY + 12}`,
    class: "feedback",
    "marker-end": "url(#arrow-feedback)",
  });
  svg.appendChild(feedback);

  const feedbackLabel = el("text", {
    x: String((fromX + toX) / 2),
    y: String(VIEW_H - 72),
    class: "feedback-label",
    "text-anchor": "middle",
  });
  feedbackLabel.textContent = "feedback: cena · stock · awaria";
  svg.appendChild(feedbackLabel);

  // Nodes.
  const groups = new Map<NodeId, SVGGElement>();
  NODES.forEach((spec, index) => {
    const x = nodeX(index);
    const group = el("g", { class: "node", "data-state": "idle" });

    const box = el("rect", {
      x: String(x),
      y: String(NODE_Y),
      width: String(NODE_W),
      height: String(NODE_H),
      rx: "12",
      class: "box",
    });
    group.appendChild(box);

    const num = el("text", { x: String(x + 14), y: String(NODE_Y + 22), class: "num" });
    num.textContent = String(spec.num);
    group.appendChild(num);

    const name = el("text", {
      x: String(x + NODE_W / 2),
      y: String(NODE_Y + 44),
      class: "name",
      "text-anchor": "middle",
    });
    name.textContent = spec.name;
    group.appendChild(name);

    const sub = el("text", {
      x: String(x + NODE_W / 2),
      y: String(NODE_Y + 66),
      class: "sub",
      "text-anchor": "middle",
    });
    sub.textContent = spec.sub;
    group.appendChild(sub);

    groups.set(spec.id, group);
    svg.appendChild(group);
  });

  container.replaceChildren(svg);

  const order: NodeId[] = NODES.map((node) => node.id);
  let feedbackTimer: number | undefined;

  function apply(activeIndex: number, warn: boolean): void {
    order.forEach((id, index) => {
      const group = groups.get(id);
      if (!group) return;
      const state = index < activeIndex ? "done" : index === activeIndex ? "active" : "idle";
      group.setAttribute("data-state", state);
      group.classList.toggle("warn", warn && index === activeIndex);
    });
    edges.forEach((edge, index) => {
      const done = index < activeIndex;
      edge.setAttribute("data-state", done ? "done" : "idle");
      edge.setAttribute("marker-end", done ? "url(#arrow-done)" : "url(#arrow-idle)");
    });
  }

  return {
    setActive(node, warn) {
      apply(order.indexOf(node), warn);
    },
    flashFeedback() {
      feedback.classList.add("on");
      window.clearTimeout(feedbackTimer);
      feedbackTimer = window.setTimeout(() => feedback.classList.remove("on"), 2600);
    },
    reset() {
      apply(-1, false);
      feedback.classList.remove("on");
    },
  };
}
