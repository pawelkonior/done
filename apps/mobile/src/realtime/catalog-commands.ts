import { searchCatalogProducts } from "@/api/client";
import type { RealtimeCommand } from "@/realtime/events";
import type {
  CatalogOffer,
  CatalogSearchInput,
  CatalogSearchResponse,
} from "@/types/domain";

export type CatalogRealtimeCommand = Extract<
  RealtimeCommand,
  { name: "search_products" }
>;

export interface CatalogCommandOutput extends Record<string, unknown> {
  ok: true;
  action: "catalog_searched";
  source: "researched_catalog";
  executable: false;
  query: string;
  total: number;
  returned: number;
  complete: boolean;
  offers: CatalogOffer[];
}

export interface CatalogCommandResult {
  result: CatalogSearchResponse;
  output: CatalogCommandOutput;
}

export class CatalogCommandRejected extends Error {
  constructor(
    readonly code: "CATALOG_SEARCH_FAILED",
    message: string,
  ) {
    super(message);
    this.name = "CatalogCommandRejected";
  }
}

export async function executeCatalogRealtimeCommand(
  command: CatalogRealtimeCommand,
): Promise<CatalogCommandResult> {
  const input: CatalogSearchInput = {
    q: command.query,
    store_id: command.storeId,
    product_id: command.productId,
    category: command.category,
    effective_status: command.effectiveStatus,
    available: command.available,
    min_price_cents: command.minPriceCents,
    max_price_cents: command.maxPriceCents,
    sort: command.sort,
    limit: 150,
    offset: 0,
  };

  let result: CatalogSearchResponse;
  try {
    result = await searchCatalogProducts(input);
  } catch {
    throw new CatalogCommandRejected(
      "CATALOG_SEARCH_FAILED",
      "The researched product catalog could not be searched. Please try again.",
    );
  }

  const returned = result.offers.length;
  return {
    result,
    output: {
      ok: true,
      action: "catalog_searched",
      source: "researched_catalog",
      executable: false,
      query: command.query,
      total: result.total,
      returned,
      complete: returned === result.total,
      offers: result.offers,
    },
  };
}
