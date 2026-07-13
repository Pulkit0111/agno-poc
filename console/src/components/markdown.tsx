"use client";

import ReactMarkdown, { type Components } from "react-markdown";

// Small, safe renderer for skill docs (SKILL.md bodies) and drafted previews.
// Deliberately does NOT pass through raw HTML (no rehype-raw) — react-markdown's
// default behavior renders any embedded HTML as inert escaped text instead of
// markup, which is the sanitization boundary this component relies on. Do not
// add rehype-raw here without re-introducing a sanitizer alongside it.
const components: Components = {
  h1: ({ ...props }) => <h1 className="font-display mb-2 text-lg text-foreground" {...props} />,
  h2: ({ ...props }) => <h2 className="mt-5 mb-1.5 text-[13.5px] font-semibold text-foreground" {...props} />,
  h3: ({ ...props }) => <h3 className="mt-4 mb-1 text-sm font-semibold text-foreground" {...props} />,
  p: ({ ...props }) => <p className="text-sm leading-relaxed text-muted-foreground" {...props} />,
  ul: ({ ...props }) => <ul className="my-1.5 list-disc space-y-1 pl-5 text-sm text-muted-foreground" {...props} />,
  ol: ({ ...props }) => <ol className="my-1.5 list-decimal space-y-1 pl-5 text-sm text-muted-foreground" {...props} />,
  li: ({ ...props }) => <li className="marker:text-muted-foreground" {...props} />,
  a: ({ ...props }) => <a className="text-primary underline underline-offset-2" {...props} />,
  strong: ({ ...props }) => <strong className="font-semibold text-foreground" {...props} />,
  code: ({ ...props }) => <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs" {...props} />,
  pre: ({ ...props }) => <pre className="overflow-x-auto rounded-md bg-muted p-3 font-mono text-xs" {...props} />,
  blockquote: ({ ...props }) => (
    <blockquote className="border-l-2 border-border pl-3 text-sm text-muted-foreground" {...props} />
  ),
};

export function Markdown({ content, className }: { content: string; className?: string }) {
  return (
    <div className={`max-w-[65ch] space-y-1 ${className ?? ""}`}>
      <ReactMarkdown components={components}>{content}</ReactMarkdown>
    </div>
  );
}
