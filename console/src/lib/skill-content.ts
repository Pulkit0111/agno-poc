// Skill content round-tripping: authored skills are stored on disk/DB as a full
// SKILL.md — a `---\nname: ...\ndescription: ...\n---\n` frontmatter block followed
// by the markdown body — but the console only ever wants the user looking at (or
// editing) the body. Splitting/rejoining here keeps the frontmatter byte-for-byte
// intact across an edit so a save can never silently corrupt the name/description
// the agno Skills loader reads from it.
const FRONTMATTER_RE = /^---\r?\n[\s\S]*?\r?\n---\r?\n/;

export function splitFrontmatter(content: string): { frontmatter: string; body: string } {
  const match = content.match(FRONTMATTER_RE);
  if (!match) return { frontmatter: "", body: content };
  return { frontmatter: match[0], body: content.slice(match[0].length).replace(/^\r?\n+/, "") };
}

/** Rejoin a (possibly edited) body with the frontmatter block extracted above. */
export function joinFrontmatter(frontmatter: string, body: string): string {
  const trimmedBody = `${body.trim()}\n`;
  return frontmatter ? `${frontmatter}\n${trimmedBody}` : trimmedBody;
}
