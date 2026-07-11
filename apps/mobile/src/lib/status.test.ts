import { isTerminal, statusToStep } from "@/lib/status";

describe("mission status mapping", () => {
  it("maps workflow states to visible steps", () => {
    expect(statusToStep("understanding")).toBe(1);
    expect(statusToStep("approval_required")).toBe(4);
    expect(statusToStep("completed")).toBe(6);
  });

  it("recognizes terminal states", () => {
    expect(isTerminal("completed")).toBe(true);
    expect(isTerminal("cancelled")).toBe(true);
    expect(isTerminal("recovering")).toBe(false);
  });
});

