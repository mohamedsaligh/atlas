import { Check, Copy } from "lucide-react";
import { memo, useEffect, useState } from "react";
import { codeToHtml } from "shiki/bundle/web";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";

export interface CodeBlockProps {
  code: string;
  lang?: string;
  /** Optional caption shown above the block — file:line or signature line. */
  caption?: string;
  /** Starting line number; defaults to 1. */
  startLine?: number;
  className?: string;
}

const THEME = "github-dark-default";

/**
 * Shiki-rendered code block. Highlighting runs once, asynchronously,
 * and the rendered HTML is cached in component state. We keep the
 * Shiki import path on the lightweight bundle/web entry to avoid
 * pulling the full grammar set.
 */
function CodeBlockInner({ code, lang = "java", caption, startLine = 1, className }: CodeBlockProps) {
  const [html, setHtml] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void codeToHtml(code, { lang, theme: THEME })
      .then((rendered) => {
        if (!cancelled) setHtml(rendered);
      })
      .catch(() => {
        if (!cancelled) setHtml(null);
      });
    return () => {
      cancelled = true;
    };
  }, [code, lang]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // ignore — clipboard may be unavailable in insecure contexts
    }
  }

  return (
    <div className={cn("group relative rounded-lg border border-border bg-bg-inset", className)}>
      {caption && (
        <div className="flex items-center justify-between border-b border-border/70 px-3 py-1.5 text-[11px] text-fg-muted">
          <span className="font-mono">{caption}</span>
          <Button
            type="button"
            intent="ghost"
            size="sm"
            onClick={copy}
            aria-label="Copy code"
            className="h-6 px-2 text-[11px]"
          >
            {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
            {copied ? "copied" : "copy"}
          </Button>
        </div>
      )}
      <div className="relative max-h-[640px] overflow-auto text-[12.5px] leading-[1.6]">
        {html ? (
          <div
            // Shiki produces a self-contained <pre><code>; we style the
            // wrapper for line numbers via CSS counter on the wrapping div.
            style={{ ["--shiki-start" as string]: startLine }}
            className="[&_pre]:!m-0 [&_pre]:!bg-transparent [&_pre]:p-3.5"
            // Trusted: Shiki output is the only source.
            dangerouslySetInnerHTML={{ __html: html }}
          />
        ) : (
          <pre className="p-3.5 font-mono text-fg/90">{code}</pre>
        )}
      </div>
    </div>
  );
}

export const CodeBlock = memo(CodeBlockInner);
