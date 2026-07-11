import { productName } from "./detail";
import type { BasketItem, CatalogOffer, NodeDetail } from "./types";

export type CheckoutSimulationPhase =
  | "idle"
  | "batch1_processing"
  | "batch1_purchased"
  | "batch2_declined";

export interface CheckoutRoute {
  batch: 1 | 2;
  storeId: string;
  storeName: string;
  endpoint: string;
  items: BasketItem[];
}

interface Store {
  id: string;
  name: string;
}

function selectStores(offers: CatalogOffer[]): Store[] {
  const stores = new Map<string, Store>();
  for (const offer of offers.filter((item) => item.is_available)) {
    stores.set(offer.store_id, { id: offer.store_id, name: offer.store_name });
  }
  const priority = ["store-delio", "store-smyk"];
  const preferred = priority.map((id) => stores.get(id)).filter((store): store is Store => Boolean(store));
  return preferred.length >= 2 ? preferred.slice(0, 2) : [...stores.values()].slice(0, 2);
}

export function buildCheckoutRoutes(items: BasketItem[], offers: CatalogOffer[]): CheckoutRoute[] {
  const stores = selectStores(offers);
  if (items.length === 0 || stores.length < 2) return [];
  const split = Math.ceil(items.length / 2);
  return stores.slice(0, 2).map((store, index) => ({
    batch: index === 0 ? 1 : 2,
    storeId: store.id,
    storeName: store.name,
    endpoint: `GET /v1/catalog/offers?store_id=${store.id}&available=true`,
    items: index === 0 ? items.slice(0, split) : items.slice(split),
  }));
}

function routeItems(route: CheckoutRoute): string {
  return route.items.map((item) => `${productName(item.product_id)} ×${item.quantity}`).join(" · ");
}

export function storeRouteDetails(routes: CheckoutRoute[]): NodeDetail[] {
  return routes.map((route) => ({
    title: `Batch ${route.batch} → ${route.storeName}`,
    meta: route.endpoint,
    description: `Connected products: ${routeItems(route)}.`,
    tone: "info",
  }));
}

export function storeBatchDetails(routes: CheckoutRoute[], phase: CheckoutSimulationPhase): NodeDetail[] {
  if (routes.length < 2) {
    return [{
      title: "Store batches pending",
      meta: "Waiting for two catalog store groups",
      description: "The dashboard reads GET /v1/catalog/offers to create purchase batches.",
      tone: "info",
    }];
  }

  return routes.map((route) => {
    const first = route.batch === 1;
    const purchased = first && (phase === "batch1_purchased" || phase === "batch2_declined");
    const processing = first && phase === "batch1_processing";
    const declined = !first && phase === "batch2_declined";
    const waiting = !first && (phase === "idle" || phase === "batch1_processing");
    const outcome = declined
      ? "PSP_SIM declined this batch. No order is created; an event triggers a projection recalculation."
      : purchased
        ? "PSP_SIM authorised this batch. Products move to Result and projection revision advances."
        : processing
          ? "Payment request is in progress for this store group."
          : waiting
            ? "This batch waits for the first store group to finish."
            : "Ready for its checkout window.";
    return {
      title: `Batch ${route.batch} · ${route.storeName}`,
      meta: route.endpoint,
      description: `${routeItems(route)}. ${outcome}`,
      tone: declined ? "error" : purchased ? "ok" : processing || waiting ? "warn" : "info",
    };
  });
}
