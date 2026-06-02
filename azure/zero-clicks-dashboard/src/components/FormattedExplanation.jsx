import React from "react";

const LIST_ITEM_RE = /^[-•*]\s+/;

function renderInline(text) {
  const segments = [];
  let remaining = String(text);
  let key = 0;

  while (remaining.length > 0) {
    const boldStart = remaining.indexOf("**");
    if (boldStart === -1) {
      segments.push(...splitAmounts(remaining, key));
      break;
    }
    if (boldStart > 0) {
      segments.push(...splitAmounts(remaining.slice(0, boldStart), key));
      key = segments.length;
      remaining = remaining.slice(boldStart);
    }
    const boldEnd = remaining.indexOf("**", 2);
    if (boldEnd === -1) {
      segments.push(...splitAmounts(remaining, key));
      break;
    }
    const inner = remaining.slice(2, boldEnd);
    segments.push(<strong key={key++}>{inner}</strong>);
    remaining = remaining.slice(boldEnd + 2);
    key = segments.length;
  }

  return segments.length ? segments : text;
}

function splitAmounts(text, startKey) {
  const parts = [];
  const re = /(\$[\d,]+(?:\.\d{2})?)/g;
  let last = 0;
  let key = startKey;
  let match;
  while ((match = re.exec(text)) !== null) {
    if (match.index > last) {
      parts.push(text.slice(last, match.index));
    }
    parts.push(
      <span key={key++} className="bill-amount">
        {match[0]}
      </span>
    );
    last = match.index + match[0].length;
  }
  if (last < text.length) {
    parts.push(text.slice(last));
  }
  return parts;
}

function classifyLine(line) {
  const trimmed = line.trim();
  if (!trimmed) return { type: "blank" };
  if (LIST_ITEM_RE.test(trimmed)) {
    return { type: "list", text: trimmed.replace(LIST_ITEM_RE, "") };
  }
  if (/^subtotal/i.test(trimmed)) {
    return { type: "subtotal", text: trimmed };
  }
  if (/=\s*\$/.test(trimmed) && !/^total/i.test(trimmed)) {
    return { type: "math", text: trimmed };
  }
  if (/^✅/.test(trimmed) || /\*\*Total:\*\*/i.test(trimmed) || /^total\s*:/i.test(trimmed)) {
    return { type: "total", text: trimmed };
  }
  return { type: "paragraph", text: trimmed };
}

function parseBlocks(text) {
  const lines = String(text).split("\n");
  const blocks = [];
  let listItems = [];

  const flushList = () => {
    if (listItems.length) {
      blocks.push({ type: "list", items: [...listItems] });
      listItems = [];
    }
  };

  for (const line of lines) {
    const row = classifyLine(line);
    if (row.type === "blank") {
      flushList();
      continue;
    }
    if (row.type === "list") {
      listItems.push(row.text);
      continue;
    }
    flushList();
    blocks.push(row);
  }
  flushList();
  return blocks;
}

export function FormattedExplanation({ text, className = "" }) {
  if (!text) return null;

  const blocks = parseBlocks(text);

  return (
    <div className={`formatted-explanation ${className}`.trim()}>
      {blocks.map((block, i) => {
        if (block.type === "list") {
          return (
            <ul key={i} className="bill-line-items">
              {block.items.map((item, j) => (
                <li key={j}>{renderInline(item)}</li>
              ))}
            </ul>
          );
        }
        if (block.type === "subtotal") {
          return (
            <p key={i} className="bill-subtotal">
              {renderInline(block.text)}
            </p>
          );
        }
        if (block.type === "math") {
          return (
            <p key={i} className="bill-math">
              {renderInline(block.text)}
            </p>
          );
        }
        if (block.type === "total") {
          return (
            <p key={i} className="bill-total">
              {renderInline(block.text)}
            </p>
          );
        }
        return (
          <p key={i} className="bill-paragraph">
            {renderInline(block.text)}
          </p>
        );
      })}
    </div>
  );
}
