import { fireEvent, render } from "@testing-library/react-native";
import { Text } from "react-native";
import { ChoiceRow, PreferenceModal } from "@/components/PreferenceModal";

jest.mock("lucide-react-native", () => ({ X: () => null }));
jest.mock("expo-linear-gradient", () => {
  const React = require("react");
  const { View } = require("react-native");
  return { LinearGradient: ({ children, ...props }: { children?: React.ReactNode }) => React.createElement(View, props, children) };
});

describe("PreferenceModal", () => {
  it("submits and closes an editable preference", async () => {
    const onClose = jest.fn();
    const onSave = jest.fn();
    const screen = await render(
      <PreferenceModal visible title="Edit preference" onClose={onClose} onSave={onSave} testID="preference">
        <Text>Editable content</Text>
      </PreferenceModal>,
    );

    await fireEvent.press(screen.getByTestId("preference-save"));
    expect(onSave).toHaveBeenCalledTimes(1);

    await fireEvent.press(screen.getByLabelText("Close"));
    expect(onClose).toHaveBeenCalledTimes(1);
    await screen.unmount();
  });

  it("exposes selected state and changes a choice", async () => {
    const onPress = jest.fn();
    const screen = await render(
      <ChoiceRow label="Balanced" description="Recommended" selected onPress={onPress} testID="balanced-choice" />,
    );

    expect(screen.getByTestId("balanced-choice").props.accessibilityState).toEqual({ checked: true });
    await fireEvent.press(screen.getByTestId("balanced-choice"));
    expect(onPress).toHaveBeenCalledTimes(1);
    await screen.unmount();
  });
});
