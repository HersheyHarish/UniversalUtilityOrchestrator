import React from "react";

const AMOUNT_RE = /(\$[\d,]+(?:\.\d{2})?)/g;

function renderInline(text) {
  const segments = [];
  let remaining = String(text);
  let key = 0;

  while (remaining.length > 0) {
    const boldStart = remaining.indexOf("**");
    if (boldStart === -1) {
      remaining.split(AMOUNT_RE).forEach((p) => {
        if (p.startsWith("$")) {
          segments.push(
            <span key={key++} className="bill-amount">
              {p}
            </span>
          );
        } else if (p) segments.push(p);
      });
      break;
    }
    if (boldStart > 0) segments.push(remaining.slice(0, boldStart));
    remaining = remaining.slice(boldStart);
    const boldEnd = remaining.indexOf("**", 2);
    if (boldEnd === -1) {
      segments.push(remaining);
      break;
    }
    segments.push(<strong key={key++}>{remaining.slice(2, boldEnd)}</strong>);
    remaining = remaining.slice(boldEnd + 2);
  }
  return segments.length ? segments : text;
}

function renderProse(content) {
  const lines = String(content).split("\n");
  const nodes = [];
  let listItems = [];
  let key = 0;

  const flushList = () => {
    if (!listItems.length) return;
    nodes.push(
      <ul key={`ul-${key++}`} className="message-list">
        {listItems.map((item, i) => (
          <li key={i}>{renderInline(item)}</li>
        ))}
      </ul>
    );
    listItems = [];
  };

  for (const line of lines) {
    const trimmed = line.trim();
    if (/^[-•*]\s+/.test(trimmed)) {
      listItems.push(trimmed.replace(/^[-•*]\s+/, ""));
      continue;
    }
    flushList();
    if (!trimmed) nodes.push(<br key={`br-${key++}`} />);
    else {
      nodes.push(
        <p key={`p-${key++}`} className="message-paragraph">
          {renderInline(line)}
        </p>
      );
    }
  }
  flushList();
  return nodes;
}

export function MessageContent({ content, segments }) {
  const blocks =
    segments && segments.length
      ? segments
      : [{ type: "prose", content: content || "" }];

  return (
    <div className="message-content">
      {blocks.map((seg, idx) => {
        if (seg.type === "code" || seg.type === "ascii") {
          return (
            <pre
              key={idx}
              className={seg.type === "ascii" ? "message-ascii" : "message-code"}
            >
              {seg.content}
            </pre>
          );
        }
        return (
          <div key={idx} className="message-prose">
            {renderProse(seg.content)}
          </div>
        );
      })}
    </div>
  );
}
