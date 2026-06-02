import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export default function MessageContent({ content, segments }) {
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
          <div key={idx} className="message-prose markdown-body">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{seg.content || ""}</ReactMarkdown>
          </div>
        );
      })}
    </div>
  );
}
