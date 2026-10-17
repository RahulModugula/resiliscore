"use client";

import { useEffect, useRef } from "react";
import type { CameraControlsImpl } from "@react-three/drei";
import { useFrame, useThree } from "@react-three/fiber";
import { Mesh, Vector3 } from "three";

/** Opt-in benchmark hook. No samples, timers, or renderer wrapper in normal use. */
export function SceneDiagnostics() {
  const state = useThree();
  const started = useRef(0);
  const enabled = useRef(false);
  useFrame(() => { if (enabled.current) started.current = performance.now(); }, -1000);
  useEffect(() => {
    if (!new URLSearchParams(location.search).has("scenePerf")) return;
    enabled.current = true;
    const { gl, scene, camera, invalidate } = state;
    const context = gl.getContext() as WebGL2RenderingContext;
    const debug = context.getExtension("WEBGL_debug_renderer_info");
    const timer = context.getExtension("EXT_disjoint_timer_query_webgl2");
    const ids = new WeakMap<object, number>();
    let nextId = 0;
    const attributeId = (attribute: object | undefined | null) => {
      if (!attribute) return undefined;
      let id = ids.get(attribute);
      if (id == null) { id = ++nextId; ids.set(attribute, id); }
      return id;
    };
    const samples: { cpuMs: number; frameCpuMs: number; calls: number; triangles: number; gpuMs: number | null }[] = [];
    const pending: { query: WebGLQuery; sample: typeof samples[number] }[] = [];
    let frames = 0;
    const original = gl.render;
    const poll = () => {
      const disjoint = timer && context.getParameter(timer.GPU_DISJOINT_EXT);
      for (let i = pending.length - 1; i >= 0; i--) {
        const { query, sample } = pending[i];
        if (disjoint || context.getQueryParameter(query, context.QUERY_RESULT_AVAILABLE)) {
          if (!disjoint) sample.gpuMs = context.getQueryParameter(query, context.QUERY_RESULT) / 1e6;
          context.deleteQuery(query);
          pending.splice(i, 1);
        }
      }
    };
    gl.render = function (renderScene, renderCamera) {
      const query = timer ? context.createQuery() : null;
      if (query) context.beginQuery(timer.TIME_ELAPSED_EXT, query);
      const start = performance.now();
      original.call(gl, renderScene, renderCamera);
      const end = performance.now();
      if (query) context.endQuery(timer.TIME_ELAPSED_EXT);
      const sample = { cpuMs: end - start, frameCpuMs: end - started.current, calls: gl.info.render.calls, triangles: gl.info.render.triangles, gpuMs: null };
      frames++;
      if (samples.length < 2000) samples.push(sample);
      if (query) pending.push({ query, sample });
    };
    const interval = window.setInterval(poll, 50);
    const api = {
      samples,
      get frames() { return frames; },
      backend: debug ? context.getParameter(debug.UNMASKED_RENDERER_WEBGL) : context.getParameter(context.RENDERER),
      vendor: debug ? context.getParameter(debug.UNMASKED_VENDOR_WEBGL) : context.getParameter(context.VENDOR),
      gpuTimer: !!timer,
      snapshot() {
        const geometries: { id: string; name: string; position?: number; color?: number; index?: number; vertices: number; bvh: boolean }[] = [];
        scene.traverse(object => {
          const mesh = object as Mesh;
          if (!mesh.geometry) return;
          const geometry = mesh.geometry;
          geometries.push({ id: geometry.uuid, name: object.name, position: attributeId(geometry.getAttribute("position")), color: attributeId(geometry.getAttribute("color")), index: attributeId(geometry.index), vertices: geometry.getAttribute("position")?.count, bvh: !!geometry.boundsTree });
        });
        const target = new Vector3();
        camera.getWorldDirection(target);
        return { frames, geometries, camera: { position: camera.position.toArray(), direction: target.toArray() }, dpr: gl.getPixelRatio(), size: [gl.domElement.width, gl.domElement.height], memory: { ...gl.info.memory } };
      },
      camera(position: [number, number, number], target: [number, number, number]) {
        const controls = state.get().controls as CameraControlsImpl | null;
        if (controls) void controls.setLookAt(...position, ...target, false);
        else { camera.position.set(...position); camera.lookAt(...target); }
        camera.updateMatrixWorld(); invalidate();
      },
      invalidate,
      reset() { samples.length = 0; },
    };
    Object.assign(window, { __scenePerf: api });
    return () => {
      enabled.current = false;
      window.clearInterval(interval);
      gl.render = original;
      pending.forEach(({ query }) => context.deleteQuery(query));
      Reflect.deleteProperty(window, "__scenePerf");
    };
  }, [state]);
  return null;
}
