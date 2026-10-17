import { BufferAttribute, BufferGeometry, DynamicDrawUsage } from "three";

interface GroundScale {
  elevations: Float64Array;
  offsets: Float64Array;
  scale: number;
}

/** Retain unrounded elevations so switching 1x/3x never accumulates float error. */
export function groundScaleGeometry(geometry: BufferGeometry, elevations: ArrayLike<number>, offsets: ArrayLike<number>, scale = 1) {
  geometry.userData.groundScale = { elevations: Float64Array.from(elevations), offsets: Float64Array.from(offsets), scale } satisfies GroundScale;
  (geometry.getAttribute("position") as BufferAttribute).setUsage(DynamicDrawUsage);
  (geometry.getAttribute("normal") as BufferAttribute | undefined)?.setUsage(DynamicDrawUsage);
  return geometry;
}

/** Change ground height, leaving each vertex's building height or overlay lift intact. */
export function updateGroundScale(geometry: BufferGeometry, scale: number, lift?: number) {
  const data = geometry.userData.groundScale as GroundScale | undefined;
  if (!data || data.scale === scale && (lift === undefined || data.offsets[0] === lift)) return false;
  if (lift !== undefined) data.offsets.fill(lift);
  const position = geometry.getAttribute("position") as BufferAttribute;
  for (let i = 0; i < position.count; i++) position.setY(i, data.elevations[i] * scale + data.offsets[i]);
  data.scale = scale;
  position.needsUpdate = true;
  if (geometry.getAttribute("normal")) geometry.computeVertexNormals();
  geometry.computeBoundingBox();
  geometry.computeBoundingSphere();
  geometry.boundsTree?.refit();
  return true;
}
