import { productName } from "./detail";
import type { CatalogOffer } from "./types";

interface StoreBatch {
  storeId: string;
  storeName: string;
  offers: CatalogOffer[];
}

export interface StoreBatchFlow {
  update(offers: CatalogOffer[], simulateSecondDecline: boolean): void;
  reset(): void;
}

function money(value: number, currency: string): string {
  return new Intl.NumberFormat("en-GB", {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(value);
}

function selectBatches(offers: CatalogOffer[]): StoreBatch[] {
  const grouped = new Map<string, StoreBatch>();
  for (const offer of offers.filter((item) => item.is_available)) {
    const batch = grouped.get(offer.store_id) ?? {
      storeId: offer.store_id,
      storeName: offer.store_name,
      offers: [],
    };
    if (batch.offers.length < 2) batch.offers.push(offer);
    grouped.set(offer.store_id, batch);
  }
  const priority = ["store-delio", "store-smyk"];
  const selected = priority.map((id) => grouped.get(id)).filter((batch): batch is StoreBatch => Boolean(batch));
  if (selected.length >= 2) return selected.slice(0, 2);
  return [...grouped.values()].filter((batch) => batch.offers.length > 0).slice(0, 2);
}

function card(batch: StoreBatch, index: number, simulateSecondDecline: boolean): HTMLElement {
  const isSecond = index === 1;
  const simulated = simulateSecondDecline;
  const state = !simulated ? (isSecond ? "scheduled" : "ready") : (isSecond ? "failed" : "paid");
  const root = document.createElement("article");
  root.className = "store-batch";
  root.dataset.state = state;

  const header = document.createElement("div");
  header.className = "store-batch-header";
  const title = document.createElement("strong");
  title.textContent = `Batch ${index + 1} · ${batch.storeName}`;
  const status = document.createElement("span");
  status.textContent = state === "failed" ? "PAYMENT DECLINED" : state === "paid" ? "PAID" : state === "ready" ? "READY" : "SCHEDULED";
  header.append(title, status);

  const endpoint = document.createElement("code");
  endpoint.className = "store-endpoint";
  endpoint.textContent = `GET /v1/catalog/offers?store_id=${batch.storeId}&available=true`;

  const items = document.createElement("div");
  items.className = "store-batch-items";
  for (const offer of batch.offers) {
    const item = document.createElement("span");
    item.textContent = `${productName(offer.product_id)} · ${money(offer.price, offer.currency)} · ${offer.sku}`;
    items.append(item);
  }

  const outcome = document.createElement("p");
  outcome.className = "store-batch-outcome";
  outcome.textContent = !simulated
    ? isSecond
      ? "Queued as the next store group."
      : "Ready for the first payment window."
    : isSecond
      ? "PSP_SIM declined this store group. No order is created for Batch 2."
      : "PSP_SIM authorised Batch 1. The group advances to order confirmation.";

  root.append(header, endpoint, items, outcome);
  return root;
}

export function createStoreBatchFlow(container: HTMLElement): StoreBatchFlow {
  return {
    update(offers, simulateSecondDecline) {
      container.replaceChildren();
      const batches = selectBatches(offers);
      if (batches.length < 2) {
        container.className = "store-batches store-batches-empty";
        container.textContent = "Waiting for at least two available store groups from the catalog endpoint.";
        return;
      }

      container.className = "store-batches";
      const heading = document.createElement("div");
      heading.className = "store-batches-heading";
      const title = document.createElement("strong");
      title.textContent = "Node 6 · Store payment batches";
      const hint = document.createElement("span");
      hint.textContent = simulateSecondDecline
        ? "Simulation: Batch 1 succeeds, Batch 2 is declined."
        : "Uses live, read-only catalog endpoints for each store.";
      heading.append(title, hint);

      const groups = document.createElement("div");
      groups.className = "store-batch-groups";
      batches.forEach((batch, index) => groups.append(card(batch, index, simulateSecondDecline)));
      container.append(heading, groups);
    },
    reset() {
      container.replaceChildren();
      container.className = "store-batches store-batches-empty";
    },
  };
}
