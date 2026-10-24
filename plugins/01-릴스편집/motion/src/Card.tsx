import React from "react";
import { AbsoluteFill, Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig, continueRender, delayRender } from "remotion";

export type CardProps = {
  kind: "price" | "list" | "counter" | "ending";
  seconds: number;
  background: string; // public/ 안의 파일 이름 (흐리게 깔리는 배경)
  accent: string;
  eyebrow?: string;
  title: string;
  lines?: string[];
  number?: number;
  unit?: string;
};

const fontHandle = delayRender("fonts");
Promise.all(
  [["500", "NotoSansKR-500.ttf"], ["900", "NotoSansKR-900.ttf"]].map(([w, f]) =>
    new FontFace("NotoKR", `url(${staticFile("fonts/" + f)})`, { weight: w }).load().then((ff) => document.fonts.add(ff)),
  ),
).then(() => continueRender(fontHandle));

const outline = "0 4px 0 rgba(0,0,0,.35), 0 0 24px rgba(0,0,0,.45)";

export const Card: React.FC<CardProps> = (p) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const enter = spring({ frame, fps, config: { damping: 14, stiffness: 160 } });
  const exit = interpolate(frame, [durationInFrames - 6, durationInFrames], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const zoom = interpolate(frame, [0, durationInFrames], [1.08, 1.0]);
  const pop = (delay: number) => spring({ frame: frame - delay, fps, config: { damping: 12, stiffness: 180 } });

  return (
    <AbsoluteFill style={{ background: "#111", fontFamily: "NotoKR, sans-serif", color: "white" }}>
      {p.background ? (
        <AbsoluteFill style={{ transform: `scale(${zoom})` }}>
          <Img src={staticFile(p.background)} style={{ width: "100%", height: "100%", objectFit: "cover", filter: "blur(28px) brightness(.45) saturate(1.2)" }} />
        </AbsoluteFill>
      ) : null}
      <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", padding: "360px 90px 0", opacity: exit }}>
        {p.eyebrow ? (
          <div style={{ fontSize: 54, fontWeight: 500, padding: "10px 34px", borderRadius: 999, background: p.accent, transform: `scale(${pop(0)})`, marginBottom: 46 }}>
            {p.eyebrow}
          </div>
        ) : null}
        {p.kind === "counter" ? <Counter {...p} frame={frame} fps={fps} /> : null}
        <div style={{ fontSize: p.kind === "price" ? 132 : 104, fontWeight: 900, lineHeight: 1.15, textAlign: "center", textShadow: outline, transform: `translateY(${(1 - enter) * 80}px)`, opacity: enter, whiteSpace: "pre-line", letterSpacing: -2 }}>
          {p.title}
        </div>
        <div style={{ marginTop: 52, display: "flex", flexDirection: "column", gap: 26, alignItems: p.kind === "list" ? "flex-start" : "center" }}>
          {(p.lines || []).map((line, i) => {
            const s = pop(6 + i * 5);
            return (
              <div key={i} style={{ fontSize: 64, fontWeight: 500, textShadow: outline, opacity: s, transform: `translateX(${(1 - s) * -60}px)`, display: "flex", alignItems: "center", gap: 22 }}>
                {p.kind === "list" ? <span style={{ width: 54, height: 54, borderRadius: 14, background: p.accent, display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: 40, fontWeight: 900 }}>✓</span> : null}
                <span>{line}</span>
              </div>
            );
          })}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const Counter: React.FC<CardProps & { frame: number; fps: number }> = ({ number = 0, unit = "", accent, frame, fps }) => {
  const value = Math.round(interpolate(frame, [0, fps * 0.8], [0, number], { extrapolateRight: "clamp", easing: (t) => 1 - Math.pow(1 - t, 3) }));
  return (
    <div style={{ fontSize: String(number).length > 3 ? 210 : 300, fontWeight: 900, color: accent, lineHeight: 1, textShadow: outline, marginBottom: 20, fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" }}>
      {value.toLocaleString("ko-KR")}
      <span style={{ fontSize: String(number).length > 3 ? 90 : 120, color: "white" }}>{unit}</span>
    </div>
  );
};
