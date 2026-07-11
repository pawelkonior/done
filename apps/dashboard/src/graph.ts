import { NODES } from "./mapping";
import { formatMoney, paymentDisplay, paymentIncident, purchaseStages, purchaseState } from "./detail";
import type { CartSnapshot, MissionDetail, NodeDetail, NodeDetails, NodeId, NodeSubtitles, ProductStoreRoute } from "./types";

const SVG_NS = "http://www.w3.org/2000/svg";

export interface Graph {
  setActive(node: NodeId, warn: boolean): void;
  setNodeSubtitles(subtitles: NodeSubtitles): void;
  setNodeDetails(details: NodeDetails): void;
  setCartSnapshot(snapshot: CartSnapshot | null): void;
  setCartCheckout(detail: MissionDetail | null): void;
  setTopology(products: ProductStoreRoute[]): void;
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

function topologyState(product: ProductStoreRoute): string {
  return product.state === "failed" ? "error" : product.state === "purchased" ? "ok" : product.state === "processing" ? "warn" : "default";
}

export function createGraph(container: HTMLElement): Graph {
  container.replaceChildren();
  container.classList.add("workflow-topology");

  const nodes = new Map<NodeId, NodeParts>();
  const steps = document.createElement("section");
  steps.className = "topology-steps";

  for (const spec of NODES) {
    const root = document.createElement("article");
    root.className = "topology-node";
    root.dataset.node = spec.id;
    root.dataset.state = "idle";
    const header = document.createElement("div");
    header.className = "topology-node-header";
    const number = document.createElement("span");
    number.className = "topology-node-number";
    number.textContent = String(spec.num);
    const name = document.createElement("h2");
    name.textContent = spec.name;
    header.append(number, name);
    const subtitle = document.createElement("p");
    subtitle.className = "topology-node-subtitle";
    subtitle.textContent = spec.sub;
    const details = document.createElement("div");
    details.className = "topology-node-details";
    root.append(header, subtitle, details);
    nodes.set(spec.id, { root, subtitle, details });
    steps.append(root);
  }

  const map = document.createElement("section");
  map.className = "topology-map";
  const routeSvg = document.createElementNS(SVG_NS, "svg");
  routeSvg.classList.add("topology-route-lines");
  routeSvg.setAttribute("aria-hidden", "true");
  const routeDefs = document.createElementNS(SVG_NS, "defs");
  for (const [state, color] of [["default", "#a78bfa"], ["ok", "#4ef0c4"], ["warn", "#ffae33"], ["error", "#ff5d73"]]) {
    const marker = document.createElementNS(SVG_NS, "marker");
    marker.setAttribute("id", `route-arrow-${state}`);
    marker.setAttribute("viewBox", "0 0 10 10");
    marker.setAttribute("refX", "9");
    marker.setAttribute("refY", "5");
    marker.setAttribute("markerWidth", "6");
    marker.setAttribute("markerHeight", "6");
    marker.setAttribute("orient", "auto");
    const tip = document.createElementNS(SVG_NS, "path");
    tip.setAttribute("d", "M 0 0 L 10 5 L 0 10 z");
    tip.setAttribute("fill", color);
    marker.append(tip);
    routeDefs.append(marker);
  }
  routeSvg.append(routeDefs);
  const cart = document.createElement("section");
  cart.className = "topology-cart";
  const cartHeading = document.createElement("div");
  cartHeading.className = "topology-heading";
  cartHeading.innerHTML = "<strong>Cart products</strong><span>Store-connected purchase routes</span>";
  const cartMetrics = document.createElement("div");
  cartMetrics.className = "topology-cart-metrics";
  const cartUpdate = document.createElement("p");
  cartUpdate.className = "topology-cart-update";
  const productList = document.createElement("div");
  productList.className = "topology-products";
  const cartCheckout = document.createElement("section");
  cartCheckout.className = "topology-checkout";
  cart.append(cartHeading, cartMetrics, cartUpdate, productList, cartCheckout);
  const shops = document.createElement("section");
  shops.className = "topology-shops";
  const shopsHeading = document.createElement("div");
  shopsHeading.className = "topology-heading";
  shopsHeading.innerHTML = "<strong>Identified shops</strong><span>Catalog endpoints</span>";
  const shopList = document.createElement("div");
  shopList.className = "topology-shop-list";
  shops.append(shopsHeading, shopList);
  map.append(routeSvg, cart, shops);

  const feedback = document.createElement("div");
  feedback.className = "topology-feedback";
  feedback.textContent = "Feedback loop: prices, inventory and payment outcomes recalculate the cart projection.";
  container.append(steps, map, feedback);

  let feedbackTimer: number | undefined;
  let topology: ProductStoreRoute[] = [];
  let animationFrame: number | undefined;
  const resizeObserver = new ResizeObserver(() => queueRouteDraw());
  resizeObserver.observe(map);

  function queueRouteDraw(): void {
    if (animationFrame !== undefined) window.cancelAnimationFrame(animationFrame);
    animationFrame = window.requestAnimationFrame(drawRoutes);
  }

  function drawRoutes(): void {
    routeSvg.replaceChildren(routeDefs);
    const bounds = map.getBoundingClientRect();
    routeSvg.setAttribute("viewBox", `0 0 ${Math.max(1, bounds.width)} ${Math.max(1, bounds.height)}`);
    routeSvg.setAttribute("width", String(Math.max(1, bounds.width)));
    routeSvg.setAttribute("height", String(Math.max(1, bounds.height)));
    for (const product of topology) {
      const source = productList.querySelector<HTMLElement>(`[data-product-id="${product.productId}"]`);
      const target = shopList.querySelector<HTMLElement>(`[data-store-id="${product.storeId}"]`);
      if (!source || !target) continue;
      const from = source.getBoundingClientRect();
      const to = target.getBoundingClientRect();
      const x1 = from.right - bounds.left;
      const y1 = from.top - bounds.top + from.height / 2;
      const x2 = to.left - bounds.left;
      const y2 = to.top - bounds.top + to.height / 2;
      const bend = Math.max(32, (x2 - x1) * 0.45);
      const path = document.createElementNS(SVG_NS, "path");
      path.classList.add("topology-route");
      const state = topologyState(product);
      path.dataset.state = state;
      path.setAttribute("d", `M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`);
      path.setAttribute("marker-end", `url(#route-arrow-${state})`);
      routeSvg.append(path);
    }
  }

  function setNodeSubtitles(values: NodeSubtitles): void {
    for (const spec of NODES) {
      const parts = nodes.get(spec.id);
      if (parts) parts.subtitle.textContent = values[spec.id] ?? spec.sub;
    }
  }

  function setNodeDetails(values: NodeDetails): void {
    for (const spec of NODES) {
      const parts = nodes.get(spec.id);
      if (parts) parts.details.replaceChildren(...(values[spec.id] ?? []).map(detailCard));
    }
  }

  function setCartSnapshot(snapshot: CartSnapshot | null): void {
    cartMetrics.replaceChildren();
    cartUpdate.textContent = "";
    if (!snapshot) return;
    for (const value of [
      `Mission: ${snapshot.status.replaceAll("_", " ")}`,
      `Progress: ${Math.round(snapshot.progress * 100)}%`,
      `Budget: ${snapshot.budgetLimit.toFixed(2)} ${snapshot.currency}`,
      `Recovered: ${snapshot.recoveredFailures}`,
    ]) {
      const metric = document.createElement("span");
      metric.textContent = value;
      cartMetrics.append(metric);
    }
    cartUpdate.textContent = snapshot.latestUpdate;
  }

  function setCartCheckout(detail: MissionDetail | null): void {
    cartCheckout.replaceChildren();
    if (!detail?.basket) return;

    const summary = document.createElement("div");
    summary.className = "topology-checkout-summary";
    const total = document.createElement("strong");
    total.textContent = `Total ${formatMoney(detail.basket.total, detail.basket.currency)}`;
    const basketMeta = document.createElement("span");
    basketMeta.textContent = [
      detail.basket.merchant?.name ?? "Merchant pending",
      `${detail.basket.item_count} items`,
      detail.basket.status.replaceAll("_", " "),
    ].join(" · ");
    summary.append(total, basketMeta);

    const purchase = purchaseState(detail);
    const purchaseCard = document.createElement("section");
    purchaseCard.className = "topology-purchase-state";
    purchaseCard.dataset.tone = purchase.tone;
    const purchaseHeading = document.createElement("h3");
    purchaseHeading.textContent = "Purchase state";
    const purchaseTitle = document.createElement("strong");
    purchaseTitle.textContent = purchase.title;
    const purchaseBody = document.createElement("p");
    purchaseBody.textContent = purchase.body;
    const stages = document.createElement("div");
    stages.className = "topology-purchase-stages";
    for (const stage of purchaseStages(detail)) {
      const step = document.createElement("span");
      step.dataset.state = stage.state;
      step.textContent = stage.name;
      stages.append(step);
    }
    purchaseCard.append(purchaseHeading, purchaseTitle, purchaseBody, stages);

    const payments = document.createElement("section");
    payments.className = "topology-payment-trail";
    const paymentsHeading = document.createElement("h3");
    paymentsHeading.textContent = "Payment trail";
    payments.append(paymentsHeading);
    const incident = paymentIncident(detail);
    if (incident) {
      const alert = document.createElement("div");
      alert.className = "topology-payment-incident";
      alert.dataset.tone = incident.tone;
      const title = document.createElement("strong");
      title.textContent = incident.title;
      const body = document.createElement("span");
      body.textContent = incident.body;
      alert.append(title, body);
      payments.append(alert);
    }
    if (detail.payment_attempts.length === 0) {
      const empty = document.createElement("p");
      empty.className = "topology-payment-empty";
      empty.textContent = "No payment attempt has been made.";
      payments.append(empty);
    } else {
      const paymentList = document.createElement("div");
      paymentList.className = "topology-payment-list";
      for (const payment of detail.payment_attempts.map(paymentDisplay)) {
        const row = document.createElement("article");
        row.className = "topology-payment-row";
        row.dataset.tone = payment.tone;
        const provider = document.createElement("strong");
        provider.textContent = payment.provider;
        const status = document.createElement("span");
        status.className = "topology-payment-status";
        status.textContent = payment.status;
        const paymentMeta = document.createElement("span");
        paymentMeta.className = "topology-payment-meta";
        paymentMeta.textContent = payment.detail;
        row.append(provider, status, paymentMeta);
        paymentList.append(row);
      }
      payments.append(paymentList);
    }

    cartCheckout.append(summary, purchaseCard, payments);
  }

  function setTopology(products: ProductStoreRoute[]): void {
    topology = products;
    productList.replaceChildren();
    shopList.replaceChildren();
    const grouped = new Map<string, ProductStoreRoute[]>();
    for (const product of products) {
      const items = grouped.get(product.storeId) ?? [];
      items.push(product);
      grouped.set(product.storeId, items);
      const row = document.createElement("article");
      row.className = "topology-product";
      row.dataset.productId = product.productId;
      row.dataset.state = topologyState(product);
      const title = document.createElement("strong");
      title.textContent = product.title;
      const meta = document.createElement("span");
      meta.textContent = `${product.quantity} × ${product.state}`;
      const route = document.createElement("span");
      route.className = "topology-product-route";
      route.textContent = `→ ${product.storeName}`;
      row.append(title, meta, route);
      productList.append(row);
    }
    for (const [storeId, items] of grouped) {
      const shop = document.createElement("article");
      shop.className = "topology-shop";
      shop.dataset.storeId = storeId;
      const title = document.createElement("strong");
      title.textContent = items[0].storeName;
      const endpoint = document.createElement("code");
      endpoint.textContent = items[0].endpoint;
      const summary = document.createElement("span");
      summary.textContent = `${items.length} connected products`;
      shop.append(title, endpoint, summary);
      shopList.append(shop);
    }
    queueRouteDraw();
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
    setCartSnapshot,
    setCartCheckout,
    setTopology,
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
      setCartSnapshot(null);
      setCartCheckout(null);
      setTopology([]);
      feedback.classList.remove("on");
    },
  };
}
