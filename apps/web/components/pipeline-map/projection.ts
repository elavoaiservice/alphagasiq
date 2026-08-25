// A dependency-free equirectangular projection over the continental US bounding box.
// This intentionally does NOT require a Mapbox/deck.gl token — it renders the
// digital-twin graph as a stylized network diagram positioned by lat/lon, which is
// enough for "where is this constraint, roughly" at a glance. Swapping in real
// Mapbox/deck.gl tiles later (see docs/architecture.md tech stack) is a drop-in
// replacement for this module's `project()` call, not a redesign of the graph model.

export const US_BOUNDS = { lonMin: -125, lonMax: -66, latMin: 24, latMax: 49 };

export function project(lat: number, lon: number, width: number, height: number) {
  const { lonMin, lonMax, latMin, latMax } = US_BOUNDS;
  const x = ((lon - lonMin) / (lonMax - lonMin)) * width;
  const y = ((latMax - lat) / (latMax - latMin)) * height;
  return { x, y };
}
