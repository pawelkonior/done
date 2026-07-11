import { productName } from "./detail";
import type { CatalogOffer, NodeDetail } from "./types";

interface StoreBatch {
  storeId: string;
  storeName: string;
  offers: CatalogOffer[];
}

function selectBatches(offers: CatalogOffer[]): StoreBatch[] {
  const grouped = new Map<string, StoreBatch>();
  for (const offer of offers.filter((item) => item.is_available)) {
    const batch = grouped.get(offer.store_id) ?? { storeId: offer.store_id, storeName: offer.store_name, offers: [] };
    if (batch.offers.length < 2) batch.offers.push(offer);
    grouped.set(offer.store_id, batch);
  }
  const priority = ["store-delio", "store-smyk"];
  const preferred = priority.map((id) => grouped.get(id)).filter((batch): batch is StoreBatch => Boolean(batch));
  return preferred.length >= 2 ? preferred.slice(0, 2) : [...grouped.values()].filter((batch) => batch.offers.length > 0).slice(0, 2);
}

export function storeBatchDetails(offers: CatalogOffer[], simulateSecondDecline: boolean): NodeDetail[] {
  const batches = selectBatches(offers);
  if (batches.length < 2) {
    return [{
      title: "Store batches pending",
      meta: "Waiting for two catalog store groups",
      description: "The dashboard reads GET /v1/catalog/offers to create purchase batches.",
      tone: "info",
    }];
  }

  return batches.map((batch, index) => {
    const second = index === 1;
    const state = simulateSecondDecline && second ? "error" : simulateSecondDecline && !second ? "ok" : second ? "warn" : "info";
    const outcome = simulateSecondDecline
      ? second
        ? "PSP_SIM declined Batch 2. No order is created for this group."
        : "PSP_SIM authorised Batch 1; it advances to order confirmation."
      : second
        ? "Scheduled as the next store group."
        : "Ready for the first payment window.";
    const products = batch.offers.map((offer) => `${productName(offer.product_id)} (${offer.sku})`).join(" · ");
    return {
      title: `Batch ${index + 1} · ${batch.storeName}`,
      meta: `GET /v1/catalog/offers?store_id=${batch.storeId}&available=true`,
      description: `${products}. ${outcome}`,
      tone: state,
    };
  });
}
