// Shared types for the ML Lab viewer

export interface GalleryEntry {
  business_slug: string;
  version: number;
  model: string;
  design_style: string;
  ux_scores: Record<string, number>;
  avg_ux_score: number;
  notes: string;
  timestamp: string;
  gallery_dir: string;
  entry_name?: string; // derived: last segment of gallery_dir
}

export interface GenerateRequest {
  business_name: string;
  business_type: string;
  design_style: string;
}
