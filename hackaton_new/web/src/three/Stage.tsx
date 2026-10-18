import { Canvas } from "@react-three/fiber";
import { View } from "@react-three/drei";
import * as THREE from "three";

/**
 * The single WebGL canvas of the app, fixed over the whole window. Every <MapView> is a DOM element that
 * the canvas renders into (scissored), so many views cost one context and one upload of the city.
 */
export function Stage() {
  return (
    <Canvas
      // inline: r3f's own inline style (position: relative) would beat a class
      style={{ position: "fixed", inset: 0, zIndex: 20, pointerEvents: "none" }}
      eventSource={document.getElementById("root")!}
      dpr={[1, 2]}
      gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
      onCreated={({ gl }) => {
        gl.toneMapping = THREE.ACESFilmicToneMapping;
        gl.toneMappingExposure = 1.05;
      }}
    >
      <View.Port />
    </Canvas>
  );
}
