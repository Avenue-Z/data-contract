import { describe, expect, it } from "vitest";
import { greet } from "../src/lib/greet";

describe("greet", () => {
  it("greets", () => {
    expect(greet("world")).toBe("hello, world");
  });
});
