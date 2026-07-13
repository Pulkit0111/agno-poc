import { describe, expect, it } from "vitest";
import { joinFrontmatter, splitFrontmatter } from "../skill-content";

describe("splitFrontmatter / joinFrontmatter", () => {
  it("splits a SKILL.md with frontmatter into its two parts", () => {
    const content = "---\nname: release-notes\ndescription: something\n---\n\n# Release notes\n\nBody text\n";
    const { frontmatter, body } = splitFrontmatter(content);
    expect(frontmatter).toBe("---\nname: release-notes\ndescription: something\n---\n");
    expect(body).toBe("# Release notes\n\nBody text\n");
  });

  it("returns empty frontmatter when there is none", () => {
    const content = "# Just a body\n";
    const { frontmatter, body } = splitFrontmatter(content);
    expect(frontmatter).toBe("");
    expect(body).toBe(content);
  });

  it("round-trips: join(split(x)) preserves the frontmatter block exactly", () => {
    const content = "---\nname: x\ndescription: y\n---\n\n# X\n\nHello\n";
    const { frontmatter, body } = splitFrontmatter(content);
    const rejoined = joinFrontmatter(frontmatter, body);
    expect(rejoined).toBe(content);
  });

  it("joins an edited body back onto the original frontmatter", () => {
    const rejoined = joinFrontmatter("---\nname: x\n---\n", "# Edited\n\nNew body");
    expect(rejoined).toBe("---\nname: x\n---\n\n# Edited\n\nNew body\n");
  });

  it("joins with no frontmatter when there was none to begin with", () => {
    expect(joinFrontmatter("", "# Edited")).toBe("# Edited\n");
  });
});
