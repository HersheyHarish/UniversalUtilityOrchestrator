import React from "react";

const Ic = ({ d, size = 16, style, className }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="2" strokeLinecap="round"
    strokeLinejoin="round" style={style} className={className}>
    <path d={d} />
  </svg>
);


export const IcDashboard = (p) => <Ic {...p} d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z M9 22V12h6v10" />;
export const IcAgents = (p) => <Ic {...p} d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2 M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z M23 21v-2a4 4 0 0 0-3-3.87 M16 3.13a4 4 0 0 1 0 7.75" />;
export const IcHealth = (p) => <Ic {...p} d="M22 12h-4l-3 9L9 3l-3 9H2" />;
export const IcPlus = (p) => <Ic {...p} d="M12 5v14 M5 12h14" />;
export const IcSearch = (p) => <Ic {...p} d="M21 21l-6-6m2-5a7 7 0 1 1-14 0 7 7 0 0 1 14 0" />;
export const IcEdit = (p) => <Ic {...p} d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7 M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />;
export const IcTrash = (p) => <Ic {...p} d="M3 6h18 M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />;
export const IcRefresh = (p) => <Ic {...p} d="M23 4v6h-6 M1 20v-6h6 M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />;
export const IcChevronRight = (p) => <Ic {...p} d="M9 18l6-6-6-6" />;
export const IcX = (p) => <Ic {...p} d="M18 6L6 18 M6 6l12 12" />;
export const IcDownload = (p) => <Ic {...p} d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4 M7 10l5 5 5-5 M12 15V3" />;
export const IcLogOut = (p) => <Ic {...p} d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4 M16 17l5-5-5-5 M21 12H9" />;
export const IcLink = (p) => <Ic {...p} d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71 M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />;
export const IcFilter = (p) => <Ic {...p} d="M22 3H2l8 9.46V19l4 2v-8.54L22 3z" />;
export const IcZap = (p) => <Ic {...p} d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />;
export const IcCopy = (p) => <Ic {...p} d="M8 17.929H6c-1.105 0-2-.912-2-2.036V5.036C4 3.91 4.895 3 6 3h8c1.105 0 2 .911 2 2.036v1.866m-6 .17h8c1.105 0 2 .91 2 2.035v10.857C20 21.09 19.105 22 18 22h-8c-1.105 0-2-.911-2-2.036V9.107c0-1.124.895-2.036 2-2.036z" />;
export const IcChart = (p) => <Ic {...p} d="M3 3v18h18 M9 17V9 M13 17V5 M17 17V13" />;
export const IcActivity = (p) => <Ic {...p} d="M22 12h-4l-3 9L9 3l-3 9H2" />;
export const IcBell = (p) => <Ic {...p} d="M18 8a6 6 0 0 0-9.33-5 M4 15h16 M6 17h12 M10 19h4" />;
export const IcUpload = (p) => <Ic {...p} d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4 M7 10l5-5 5 5 M12 15V3" />;