import { fireEvent, render } from "@testing-library/react-native";
import { ApprovalCard } from "@/components/ApprovalCard";
import { BasketCard } from "@/components/BasketCard";

jest.mock("lucide-react-native", () => ({
  AudioLines: () => null,
  Check: () => null,
  CheckCircle2: () => null,
  ListChecks: () => null,
  ShieldCheck: () => null,
  ShoppingBasket: () => null,
  X: () => null,
}));
jest.mock("expo-linear-gradient", () => {
  const React = require("react");
  const { View } = require("react-native");
  return { LinearGradient: ({ children, ...props }: { children?: React.ReactNode }) => React.createElement(View, props, children) };
});

describe("purchase plan cards", () => {
  it("describes approval as an exact provider-backed plan without claiming a simulated order", async () => {
    const onApprove = jest.fn();
    const screen = await render(
      <ApprovalCard
        amount={192.73}
        currency="PLN"
        loading={false}
        onApprove={onApprove}
        onCancel={jest.fn()}
      />,
    );

    expect(screen.getByText("Approve this exact plan")).toBeTruthy();
    expect(screen.getByText("192.73 PLN")).toBeTruthy();
    expect(screen.getByText(/connected commerce providers/)).toBeTruthy();
    expect(screen.queryByText(/simulate/i)).toBeNull();
    await fireEvent.press(screen.getByTestId("approve-button"));
    expect(onApprove).toHaveBeenCalledTimes(1);
    await screen.unmount();
  });

  it("labels an unexecuted basket as a validated proposal", async () => {
    const screen = await render(
      <BasketCard
        basket={{
          id: "basket-1",
          merchant: "Merchant",
          merchant_id: "merchant-1",
          status: "proposed",
          currency: "PLN",
          subtotal: 180,
          delivery_cost: 12.73,
          total: 192.73,
          items: [],
        }}
      />,
    );

    expect(screen.getByText("Proposed basket")).toBeTruthy();
    expect(screen.getByText("Validated")).toBeTruthy();
    expect(screen.getByText("192.73 PLN")).toBeTruthy();
    expect(screen.queryByText("Optimized basket")).toBeNull();
    await screen.unmount();
  });
});
