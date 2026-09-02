export const VIBES = [
  "casual", "upscale", "romantic", "lively", "cozy", "divey", "trendy", "classic", "family-friendly",
  "tourist-heavy", "locals", "quiet", "loud", "intimate", "spacious", "rustic", "modern", "kitschy",
  "no-frills", "late-night", "outdoor-seating", "counter-service", "old-school", "scene-y", "hidden-gem",
] as const;
export const CATEGORIES = ["bar", "pub", "restaurant", "cafe", "nightclub", "fast_food"] as const;
export const SOURCE_LABEL: Record<string, string> = { infatuation: "The Infatuation", wikipedia: "Wikipedia", wikivoyage: "Wikivoyage" };
export const sentimentLabel = (s: number | null) => s == null ? "—" : s > 0.33 ? "positive" : s < -0.33 ? "negative" : "mixed";
