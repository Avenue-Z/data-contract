import { describe, expect, it } from "vitest";
import { greet } from "../src/main.js";

describe("greet", () => {
  it("returns a greeting", () => {
    expect(greet("world")).toBe("hello, world");
  });
});
