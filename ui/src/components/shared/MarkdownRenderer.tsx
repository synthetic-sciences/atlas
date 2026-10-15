/**
 * Lightweight markdown-to-HTML renderer.
 * No external dependencies - regex-based conversion for common markdown syntax.
 * The input is escaped before any markdown replacement runs, so shared/public
 * node content can render markdown without turning raw HTML into executable DOM.
 */

function escapeHtml(input: string): string {
  return input
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function markdownToHtml(md: string): string {
  let html = escapeHtml(md);

  // Code blocks (``` ... ```) - must run before inline code
  html = html.replace(/```([\s\S]*?)```/g, (_match, code: string) => {
    return `<pre style="background:var(--color-surface);padding:8px 10px;border-radius:var(--radius-xs);overflow-x:auto;margin:6px 0;font-size:11px;line-height:1.5"><code>${code.trim()}</code></pre>`;
  });

  // Inline code (must run before bold/italic to avoid conflicts)
  html = html.replace(/`([^`]+)`/g, '<code style="background:var(--color-surface);padding:1px 4px;border-radius:2px;font-size:0.92em">$1</code>');

  // Headings
  html = html.replace(/^### (.+)$/gm, '<h3 style="font-size:14px;font-weight:600;margin:8px 0 4px">$1</h3>');
  html = html.replace(/^## (.+)$/gm, '<h2 style="font-size:15px;font-weight:600;margin:10px 0 4px">$1</h2>');
  html = html.replace(/^# (.+)$/gm, '<h1 style="font-size:16px;font-weight:600;margin:12px 0 4px">$1</h1>');

  // Bold and italic
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');

  // Numbered lists: consecutive lines starting with "N. "
  html = html.replace(
    /(^[0-9]+\. .+$(\n|$))+/gm,
    (block) => {
      const items = block
        .trim()
        .split("\n")
        .map((line) => line.replace(/^[0-9]+\.\s+/, ""))
        .map((text) => `<li style="margin-left:16px;list-style:decimal">${text}</li>`)
        .join("");
      return `<ol style="margin:4px 0;padding-left:4px">${items}</ol>`;
    }
  );

  // Bullet lists: consecutive lines starting with "- "
  html = html.replace(
    /(^- .+$(\n|$))+/gm,
    (block) => {
      const items = block
        .trim()
        .split("\n")
        .map((line) => line.replace(/^- /, ""))
        .map((text) => `<li style="margin-left:16px;list-style:disc">${text}</li>`)
        .join("");
      return `<ul style="margin:4px 0;padding-left:4px">${items}</ul>`;
    }
  );

  // Line breaks (but not after block elements we just inserted)
  html = html.replace(/\n/g, "<br/>");

  // Clean up double <br/> after block elements
  html = html.replace(/(<\/(?:pre|h[1-3]|ul|ol)>)<br\/>/g, "$1");

  return html;
}

interface MarkdownRendererProps {
  content: string;
  style?: React.CSSProperties;
  className?: string;
}

export function MarkdownRenderer({ content, style, className }: MarkdownRendererProps) {
  return (
    <div
      className={className}
      style={style}
      dangerouslySetInnerHTML={{ __html: markdownToHtml(content) }}
    />
  );
}
