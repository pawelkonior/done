import { searchCatalogProducts } from "@/api/client";
import {
  CatalogCommandRejected,
  executeCatalogRealtimeCommand,
} from "@/realtime/catalog-commands";
import type { CatalogOffer, CatalogSearchResponse } from "@/types/domain";

jest.mock("@/api/client", () => ({
  searchCatalogProducts: jest.fn(),
}));

function catalogOffer(index: number): CatalogOffer {
  return {
    store_id: `store-${index % 7}`,
    store_name: `Store ${index % 7}`,
    city: "Warsaw",
    product_id: `product-${index}`,
    sku: `SKU-${String(index).padStart(3, "0")}`,
    product_name: `Minecraft birthday product ${index}`,
    brand: "Birthday Brand",
    category: "gifts",
    unit_label: "1 item",
    product_url: `https://example.test/products/${index}`,
    price_cents: 1_000 + index,
    currency: "PLN",
    price_display: `${(10 + index / 100).toFixed(2)} PLN`,
    quantity: 10,
    effective_status: "available",
    is_available: true,
    updated_at: "2026-07-11T13:00:00Z",
  };
}

describe("catalog Realtime command execution", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("returns every researched offer and forwards bounded catalog filters", async () => {
    const offers = Array.from({ length: 140 }, (_, index) => catalogOffer(index));
    const response: CatalogSearchResponse = {
      offers,
      total: 140,
      limit: 150,
      offset: 0,
    };
    jest.mocked(searchCatalogProducts).mockResolvedValue(response);

    const result = await executeCatalogRealtimeCommand({
      name: "search_products",
      callId: "call-catalog",
      query: "Minecraft",
      storeId: "store-allegro",
      productId: "product-42",
      category: "gifts",
      effectiveStatus: "available",
      available: true,
      minPriceCents: 1_000,
      maxPriceCents: 20_000,
      sort: "price_asc",
    });

    expect(searchCatalogProducts).toHaveBeenCalledWith({
      q: "Minecraft",
      store_id: "store-allegro",
      product_id: "product-42",
      category: "gifts",
      effective_status: "available",
      available: true,
      min_price_cents: 1_000,
      max_price_cents: 20_000,
      sort: "price_asc",
      limit: 150,
      offset: 0,
    });
    expect(result.result).toBe(response);
    expect(result.output).toMatchObject({
      ok: true,
      action: "catalog_searched",
      source: "researched_catalog",
      executable: false,
      query: "Minecraft",
      total: 140,
      returned: 140,
      complete: true,
    });
    expect(result.output.offers).toHaveLength(140);
    expect(result.output.offers).toEqual(offers);
    expect(result.output.offers[139]?.product_id).toBe("product-139");
  });

  it("maps API failures to a safe catalog rejection", async () => {
    jest.mocked(searchCatalogProducts).mockRejectedValue(
      new Error("upstream secret: database path and provider response"),
    );

    const execution = executeCatalogRealtimeCommand({
      name: "search_products",
      callId: "call-failed-catalog",
      query: "Minecraft",
    });

    await expect(execution).rejects.toMatchObject({
      name: "CatalogCommandRejected",
      code: "CATALOG_SEARCH_FAILED",
      message: "The researched product catalog could not be searched. Please try again.",
    });
    await expect(execution).rejects.toBeInstanceOf(CatalogCommandRejected);
    await expect(execution).rejects.not.toHaveProperty(
      "message",
      expect.stringContaining("upstream secret"),
    );
  });
});
