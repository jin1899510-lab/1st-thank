import React from "react";
import { Composition } from "remotion";
import { Card, CardProps } from "./Card";

const FPS = 30;

const defaults: CardProps = {
  kind: "list",
  seconds: 1.5,
  background: "",
  accent: "#ff5a36",
  eyebrow: "남포동",
  title: "예시 제목",
  lines: ["첫 줄", "둘째 줄"],
  number: 50,
  unit: "가지+",
};

export const Root: React.FC = () => (
  <Composition
    id="Card"
    component={Card}
    width={1080}
    height={1920}
    fps={FPS}
    durationInFrames={Math.round(defaults.seconds * FPS)}
    defaultProps={defaults}
    calculateMetadata={({ props }) => ({ durationInFrames: Math.max(15, Math.round(props.seconds * FPS)) })}
  />
);
