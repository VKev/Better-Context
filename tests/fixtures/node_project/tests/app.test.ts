import { createApp } from "../src/app";

it("greets", () => {
  expect(createApp()).toBe("Hello, world!");
});
