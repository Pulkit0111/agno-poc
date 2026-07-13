import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Markdown } from "../markdown";

describe("Markdown", () => {
  it("renders headings and lists as real elements", () => {
    const content = "# Title\n\n## Steps\n1. First step\n2. Second step\n";
    render(<Markdown content={content} />);

    const h1 = screen.getByRole("heading", { level: 1, name: "Title" });
    expect(h1).toBeDefined();
    const h2 = screen.getByRole("heading", { level: 2, name: "Steps" });
    expect(h2).toBeDefined();
    expect(screen.getByText("First step")).toBeDefined();
    expect(screen.getByText("Second step")).toBeDefined();
  });

  it("escapes raw HTML instead of executing or rendering it as markup", () => {
    const content = "Before\n\n<script>window.__pwned = true;</script>\n\nAfter";
    const { container } = render(<Markdown content={content} />);

    // No actual <script> element should ever land in the DOM.
    expect(container.querySelector("script")).toBeNull();
    // The literal text should still show up somewhere, escaped as text —
    // not silently dropped and not executed.
    expect(container.textContent).toContain("<script>");
    expect(container.textContent).toContain("window.__pwned = true;");
  });
});
