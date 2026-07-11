import { fireEvent, render } from "@testing-library/react-native";
import { ActionRequestCard } from "@/components/ActionRequestCard";
import type { ActionRequest } from "@/types/domain";

jest.mock("lucide-react-native", () => ({
  AudioLines: () => null,
  Check: () => null,
  UserRound: () => null,
}));
jest.mock("expo-linear-gradient", () => {
  const React = require("react");
  const { View } = require("react-native");
  return { LinearGradient: ({ children, ...props }: { children?: React.ReactNode }) => React.createElement(View, props, children) };
});

const pendingAction: ActionRequest = {
  id: "action-1",
  type: "recovery_choice",
  reason_code: "NO_COMPLIANT_REPLACEMENT",
  question: "The requested item is unavailable. What should I do?",
  status: "pending",
  owner: "user",
  options: [
    { id: "retry_search", label: "Search other stores" },
    { id: "request_human", label: "Ask human support" },
  ],
  created_at: "2026-07-11T10:00:00Z",
};

describe("ActionRequestCard", () => {
  it("shows the question and reason, then returns the selected choice", async () => {
    const onChoose = jest.fn();
    const screen = await render(
      <ActionRequestCard action={pendingAction} loading={false} onChoose={onChoose} />,
    );

    expect(screen.getByTestId("action-request-question")).toHaveTextContent(
      "The requested item is unavailable. What should I do?",
    );
    expect(screen.getByText("No compliant replacement")).toBeTruthy();

    await fireEvent.press(screen.getByTestId("action-choice-retry_search"));

    expect(onChoose).toHaveBeenCalledWith("retry_search");
    expect(screen.queryByTestId("action-choice-request_human")).toBeNull();
    expect(screen.getByTestId("request-human-button")).toHaveProp(
      "accessibilityLabel",
      "Talk to human support",
    );
    await screen.unmount();
  });

  it("uses the request_human option through the dedicated support button", async () => {
    const onChoose = jest.fn();
    const screen = await render(
      <ActionRequestCard action={pendingAction} loading={false} onChoose={onChoose} />,
    );

    await fireEvent.press(screen.getByTestId("request-human-button"));

    expect(onChoose).toHaveBeenCalledWith("request_human");
    expect(screen.getByLabelText("Talk to human support")).toBeTruthy();
    await screen.unmount();
  });

  it("prefers the explicit human-support callback", async () => {
    const onChoose = jest.fn();
    const onRequestHuman = jest.fn();
    const actionWithoutHumanOption = {
      ...pendingAction,
      options: pendingAction.options.filter((option) => option.id !== "request_human"),
    };
    const screen = await render(
      <ActionRequestCard
        action={actionWithoutHumanOption}
        loading={false}
        onChoose={onChoose}
        onRequestHuman={onRequestHuman}
      />,
    );

    await fireEvent.press(screen.getByTestId("request-human-button"));

    expect(onRequestHuman).toHaveBeenCalledTimes(1);
    expect(onChoose).not.toHaveBeenCalled();
    await screen.unmount();
  });

  it.each([
    ["loading", pendingAction, true],
    ["resolved", { ...pendingAction, status: "resolved" as const }, false],
  ])("disables choices when the request is %s", async (_label, action, loading) => {
    const onChoose = jest.fn();
    const screen = await render(
      <ActionRequestCard action={action} loading={loading} onChoose={onChoose} />,
    );
    const choice = screen.getByTestId("action-choice-retry_search");
    const humanSupport = screen.getByTestId("request-human-button");

    await fireEvent.press(choice);
    await fireEvent.press(humanSupport);

    expect(onChoose).not.toHaveBeenCalled();
    expect(choice.props.accessibilityState.disabled).toBe(true);
    expect(humanSupport.props.accessibilityState.disabled).toBe(true);
    await screen.unmount();
  });
});
