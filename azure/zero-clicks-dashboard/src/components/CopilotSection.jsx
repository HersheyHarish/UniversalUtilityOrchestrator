import React from "react";

const SAMPLE_ROWS = [
  { date: "2019-07-09", kwh: 28, spike: false },
  { date: "2019-07-11", kwh: 41, spike: true },
  { date: "2019-07-15", kwh: 55, spike: true },
  { date: "2019-07-22", kwh: 31, spike: false },
];

export function CopilotSection({ selectedDate, context, onDateSelect }) {
  return (
    <section className="section">
      <h2>Contextual Hover Copilot</h2>
      <p>Hover or click a spike day to inspect AI context:</p>
      <div className="card">
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th style={{ textAlign: "left", paddingBottom: 8 }}>Date</th>
              <th style={{ textAlign: "left", paddingBottom: 8 }}>kWh</th>
              <th style={{ textAlign: "left", paddingBottom: 8 }}>Flag</th>
            </tr>
          </thead>
          <tbody>
            {SAMPLE_ROWS.map((r) => (
              <tr
                key={r.date}
                onMouseEnter={() => r.spike && onDateSelect(r.date)}
                onClick={() => onDateSelect(r.date)}
                style={{ cursor: "pointer" }}
              >
                <td style={{ padding: "6px 0" }}>{r.date}</td>
                <td>{r.kwh}</td>
                <td>{r.spike ? "Spike" : "Normal"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="card" style={{ marginTop: 12 }}>
        <div className="row">
          <span className="chip">Date</span>
          <span>{selectedDate}</span>
        </div>
        <p style={{ marginBottom: 6 }}>{context?.explanation || "No context yet."}</p>
        <div className="row">
          {(context?.recommended_actions || []).map((a, idx) => (
            <span className="chip" key={`${a}-${idx}`}>
              {a}
            </span>
          ))}
        </div>
      </div>
    </section>
  );
}
