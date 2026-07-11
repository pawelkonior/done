import { NODES } from "./mapping";
import type { NodeDetail, NodeDetails, NodeId, NodeSubtitles } from "./types";

export interface Graph {
  setActive(node: NodeId, warn: boolean): void;
  setNodeSubtitles(subtitles: NodeSubtitles): void;
  setNodeDetails(details: NodeDetails): void;
  flashFeedback(): void;
  reset(): void;
}

interface NodeParts {
  root: HTMLElement;
  subtitle: HTMLElement;
  details: HTMLElement;
}

function detailCard(detail: NodeDetail): HTMLElement {
  const card = document.createElement("article");
  card.className = "workflow-detail";
  card.dataset.tone = detail.tone ?? "info";
  const title = document.createElement("strong");
  title.textContent = detail.title;
  card.append(title);
  if (detail.meta) {
    const meta = document.createElement("span");
    meta.className = "workflow-detail-meta";
    meta.textContent = detail.meta;
    card.append(meta);
  }
  if (detail.description) {
    const description = document.createElement("span");
    description.className = "workflow-detail-description";
    description.textContent = detail.description;
    card.append(description);
  }
  if (detail.route) {
    const route = document.createElement("span");
    route.className = "workflow-route-link";
    route.dataset.state = detail.route.state;
    route.textContent = detail.route.label;
    card.append(route);
  }
  return card;
}

export function createGraph(container: HTMLElement): Graph {
  container.replaceChildren();
  container.classList.add("workflow-board");

  const nodes = new Map<NodeId, NodeParts>();
  for (const spec of NODES) {
    const root = document.createElement("article");
    root.className = "workflow-node";
    root.dataset.node = spec.id;
    root.dataset.state = "idle";

    const header = document.createElement("div");
    header.className = "workflow-node-header";
    const number = document.createElement("span");
    number.className = "workflow-node-number";
    number.textContent = String(spec.num);
    const name = document.createElement("h2");
    name.textContent = spec.name;
    header.append(number, name);

    const subtitle = document.createElement("p");
    subtitle.className = "workflow-node-subtitle";
    subtitle.textContent = spec.sub;
    const details = document.createElement("div");
    details.className = "workflow-node-details";
    root.append(header, subtitle, details);
    nodes.set(spec.id, { root, subtitle, details });
    container.append(root);
  }

  const feedback = document.createElement("div");
  feedback.className = "workflow-feedback";
  feedback.textContent = "Feedback loop: price, inventory and payment outcomes return to planning.";
  container.append(feedback);
  let feedbackTimer: number | undefined;

  function setNodeSubtitles(values: NodeSubtitles): void {
    for (const spec of NODES) {
      const parts = nodes.get(spec.id);
      if (parts) parts.subtitle.textContent = values[spec.id] ?? spec.sub;
    }
  }

  function setNodeDetails(values: NodeDetails): void {
    for (const spec of NODES) {
      const parts = nodes.get(spec.id);
      if (!parts) continue;
      parts.details.replaceChildren(...(values[spec.id] ?? []).map(detailCard));
    }
  }

  return {
    setActive(active, warn) {
      const activeIndex = NODES.findIndex((node) => node.id === active);
      NODES.forEach((node, index) => {
        const parts = nodes.get(node.id);
        if (!parts) return;
        parts.root.dataset.state = index < activeIndex ? "done" : index === activeIndex ? "active" : "idle";
        parts.root.classList.toggle("warn", warn && index === activeIndex);
      });
    },
    setNodeSubtitles,
    setNodeDetails,
    flashFeedback() {
      feedback.classList.add("on");
      window.clearTimeout(feedbackTimer);
      feedbackTimer = window.setTimeout(() => feedback.classList.remove("on"), 2600);
    },
    reset() {
      for (const parts of nodes.values()) {
        parts.root.dataset.state = "idle";
        parts.root.classList.remove("warn");
      }
      setNodeSubtitles({});
      setNodeDetails({});
      feedback.classList.remove("on");
    },
  };
}
