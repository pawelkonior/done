import { productName } from "./detail";
import type { BasketItem, CatalogOffer, NodeDetail } from "./types";

export type CheckoutSimulationPhase =
  | "idle"
  | "batch1_processing"
  | "batch1_purchased"
  | "batch2_declined"
  | "batch2_rerouted";

export interface CheckoutRoute {
  batch: 1 | 2 | 3;
  storeId: string;
  storeName: string;
  endpoint: string;
  items: BasketItem[];
}

interface Store {
  id: string;
  name: string;
}

const FALLBACK_STORES: readonly Store[] = [
  { id: "store-delio", name: "delio" },
  { id: "store-smyk", name: "Smyk" },
];

const REROUTE_STORES: readonly Store[] = [
  { id: "store-partyco", name: "Party&Co" },
  { id: "store-freshday", name: "Fresh Day" },
];

function selectStores(offers: CatalogOffer[]): Store[] {
  const stores = new Map<string, Store>();
  for (const offer of offers.filter((item) => item.is_available)) {
    stores.set(offer.store_id, { id: offer.store_id, name: offer.store_name });
  }
  return FALLBACK_STORES.map((fallback) => stores.get(fallback.id) ?? fallback);
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

/** Splits a declined store group across two new stores after a replanning event. */
export function rerouteDeclinedBatch(routes: CheckoutRoute[]): CheckoutRoute[] {
  const firstBatch = routes.find((route) => route.batch === 1);
  const declinedBatch = routes.find((route) => route.batch === 2);
  if (!firstBatch || !declinedBatch || declinedBatch.items.length === 0) return routes;
  const split = Math.ceil(declinedBatch.items.length / 2);
  return [
    firstBatch,
    ...REROUTE_STORES.map((store, index) => ({
      batch: (index === 0 ? 2 : 3) as 2 | 3,
      storeId: store.id,
      storeName: store.name,
      endpoint: `GET /v1/catalog/offers?store_id=${store.id}&available=true`,
      items: index === 0 ? declinedBatch.items.slice(0, split) : declinedBatch.items.slice(split),
    })),
  ];
}

function routeItems(route: CheckoutRoute): string {
  return route.items.map((item) => `${productName(item.product_id)} ×${item.quantity}`).join(" · ");
}

export function storeRouteDetails(routes: CheckoutRoute[]): NodeDetail[] {
  return routes.map((route) => ({
    title: `Batch ${route.batch} → ${route.storeName}`,
    meta: route.endpoint,
    description: `Connected products: ${routeItems(route)}.`,
    route: {
      label: `STORE ROUTE B${route.batch}: ${route.storeName} → Node 6 Purchase`,
      state: "default",
    },
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

  if (phase === "batch2_rerouted") {
    return routes.map((route) => {
      const completed = route.batch === 1;
      return {
        title: completed ? `Batch 1 / ${route.storeName}` : `Retry batch ${route.batch} / ${route.storeName}`,
        meta: route.endpoint,
        description: completed
          ? `${routeItems(route)}. The first store group is already purchased.`
          : `${routeItems(route)}. New portfolio route: payment retry is in progress at this replacement store.`,
        route: {
          label: completed
            ? `STORE ROUTE B1: ${route.storeName} -> Result`
            : `RETRY ROUTE B${route.batch}: ${route.storeName} -> Purchase`,
          state: completed ? "ok" : "default",
        },
        tone: completed ? "ok" : "warn",
      };
    });
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
      route: {
        label: declined
          ? `STORE ROUTE B${route.batch}: ${route.storeName} → Purchase blocked`
          : `STORE ROUTE B${route.batch}: ${route.storeName} → Purchase`,
        state: declined ? "error" : purchased ? "ok" : "default",
      },
      tone: declined ? "error" : purchased ? "ok" : processing || waiting ? "warn" : "info",
    };
  });
}
