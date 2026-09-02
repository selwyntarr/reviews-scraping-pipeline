"use client";
import maplibregl from "maplibre-gl";
import { useEffect, useRef } from "react";
import type { MapVenue } from "@/lib/types";
import { useTheme } from "./ThemeShell";

const STYLES = { light: "https://tiles.openfreemap.org/styles/positron", dark: "https://tiles.openfreemap.org/styles/dark" };

function addLayers(m: maplibregl.Map, data: GeoJSON.FeatureCollection) {
  if (m.getSource("venues")) return;
  m.addSource("venues", { type: "geojson", data });
  m.addLayer({ id: "dots", type: "circle", source: "venues", filter: ["==", ["get", "insight"], 0],
    paint: { "circle-radius": ["interpolate", ["linear"], ["zoom"], 11, 1.2, 15, 3.5], "circle-color": "#94a3b8", "circle-opacity": 0.45 } });
  m.addLayer({ id: "insight", type: "circle", source: "venues", filter: ["==", ["get", "insight"], 1],
    paint: { "circle-radius": ["case", ["==", ["get", "sel"], 1], 9, ["==", ["get", "hit"], 1], 6, 4],
      "circle-color": ["case", ["==", ["get", "sel"], 1], "#fbbf24", ["==", ["get", "hit"], 1], "#4f46e5", "#a5b4fc"],
      "circle-stroke-color": "#fff", "circle-stroke-width": 1.2, "circle-opacity": ["case", ["==", ["get", "hit"], 1], 1, 0.5] } });
}

export function MapView({ venues, highlighted, selected, onSelect }: {
  venues: MapVenue[]; highlighted: Set<number>; selected: number | null; onSelect: (id: number) => void;
}) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const { mode } = useTheme();

  const geojson = (): GeoJSON.FeatureCollection => ({
    type: "FeatureCollection",
    features: venues.map((v) => ({
      type: "Feature", id: v.id, geometry: { type: "Point", coordinates: [v.lon, v.lat] },
      properties: { id: v.id, name: v.name, insight: v.has_insights ? 1 : 0, hit: highlighted.has(v.id) ? 1 : 0, sel: v.id === selected ? 1 : 0 },
    })),
  });

  useEffect(() => {
    if (!el.current || map.current) return;
    const m = new maplibregl.Map({ container: el.current, style: STYLES[mode], center: [-73.975, 40.76], zoom: 12.2, attributionControl: { compact: true } });
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
    m.on("load", () => {
      addLayers(m, geojson());
      m.on("click", "insight", (e) => { const f = e.features?.[0]; if (f) onSelect(Number(f.properties?.id)); });
      m.on("mouseenter", "insight", () => (m.getCanvas().style.cursor = "pointer"));
      m.on("mouseleave", "insight", () => (m.getCanvas().style.cursor = ""));
    });
    map.current = m;
    return () => { m.remove(); map.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const m = map.current; if (!m) return;
    const src = m.getSource("venues") as maplibregl.GeoJSONSource | undefined;
    if (src) src.setData(geojson());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [venues, highlighted, selected]);

  const lastMode = useRef(mode);
  useEffect(() => {
    const m = map.current; if (!m || lastMode.current === mode) return;
    lastMode.current = mode;
    m.setStyle(STYLES[mode]);
    m.once("style.load", () => addLayers(m, geojson()));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode]);

  useEffect(() => {
    const m = map.current; if (!m || selected == null) return;
    const v = venues.find((x) => x.id === selected);
    if (v) m.easeTo({ center: [v.lon, v.lat], zoom: Math.max(m.getZoom(), 14), duration: 500 });
  }, [selected, venues]);

  return <div ref={el} className="map" />;
}
