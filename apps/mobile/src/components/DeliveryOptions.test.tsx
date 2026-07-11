import { fireEvent, render } from "@testing-library/react-native";
import { DeliveryOptions } from "@/components/DeliveryOptions";
import type { DeliveryOption } from "@/types/domain";

jest.mock("lucide-react-native", () => ({
  CalendarClock: () => null,
  CarFront: () => null,
  Check: () => null,
  Truck: () => null,
  Zap: () => null,
}));
jest.mock("expo-linear-gradient", () => {
  const React = require("react");
  const { View } = require("react-native");
  return { LinearGradient: ({ children, ...props }: { children?: React.ReactNode }) => React.createElement(View, props, children) };
});

const options: DeliveryOption[] = [
  { id: "express", name: "Express", eta: "Tomorrow", price: 29, currency: "PLN", badge: "Fastest", selected: true },
  { id: "standard", name: "Standard", eta: "In two days", price: 15, currency: "PLN", badge: "Best value", selected: false },
];

describe("DeliveryOptions", () => {
  it("selects an available radio option", async () => {
    const onSelect = jest.fn();
    const screen = await render(<DeliveryOptions options={options} onSelect={onSelect} />);

    await fireEvent.press(screen.getByTestId("delivery-option-standard"));

    expect(onSelect).toHaveBeenCalledWith("standard");
    expect(screen.getByTestId("delivery-option-express").props.accessibilityState.checked).toBe(true);
    await screen.unmount();
  });

  it("blocks selection while the control is disabled", async () => {
    const onSelect = jest.fn();
    const screen = await render(<DeliveryOptions options={options} onSelect={onSelect} disabled />);

    await fireEvent.press(screen.getByTestId("delivery-option-standard"));

    expect(onSelect).not.toHaveBeenCalled();
    expect(screen.getByTestId("delivery-option-standard").props.accessibilityState.disabled).toBe(true);
    await screen.unmount();
  });
});
