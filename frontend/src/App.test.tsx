import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import App from "./App";

describe("foundation workspace", () => {
  it("VTX-OFF-003 explains that no active report is available", () => {
    render(<App />);
    expect(screen.getByText("No active report")).toBeInTheDocument();
    expect(screen.getByText(/open a configured project day/i)).toBeInTheDocument();
  });
});

