// Mirrors the backend Pydantic schemas (app/models).

export type Source = "darglobal" | "wasalt";
export type RecordType = "listing" | "development";
export type TransactionType = "sale" | "rent" | "unspecified";
export type PriceBasis =
  | "total"
  | "starting"
  | "monthly_rent"
  | "annual_rent"
  | "unspecified";

export interface Property {
  id: string;
  source: Source;
  source_record_id: string | null;
  record_type: RecordType;
  title: string;
  country: string | null;
  city: string | null;
  district: string | null;
  property_type: string | null;
  transaction_type: TransactionType;
  price_amount: string | null; // exact decimal serialized as string
  price_currency: string | null;
  price_basis: PriceBasis;
  original_price_text: string | null;
  bedrooms: number | null;
  bathrooms: number | null;
  area_value: string | null;
  area_unit: string | null;
  original_area_text: string | null;
  amenities: string[];
  description: string | null;
  developer: string | null;
  completion_or_handover_text: string | null;
  image_url: string | null;
  source_url: string;
  scraped_at: string;
  content_hash: string;
  evidence: { passage_id: string; document_id: string; canonical_url: string }[];
}

export interface Facet {
  value: string;
  count: number;
}
export interface Facets {
  sources?: Facet[];
  cities?: Facet[];
  property_types?: Facet[];
  record_types?: Facet[];
  transaction_types?: Facet[];
  bedrooms?: Facet[];
  currencies?: Facet[];
}

export interface PropertyListResponse {
  items: Property[];
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
  facets: Facets;
}

export interface EvidenceItem {
  id: string;
  ordinal: number;
  source: Source;
  site: string;
  title: string | null;
  section_heading: string | null;
  excerpt: string;
  url: string;
  collected_at: string;
}

export interface SourceCoverage {
  source: string;
  site: string;
  document_count: number;
  property_count: number;
  listing_count: number;
  development_count: number;
  latest_collection: string | null;
  cities: string[];
  record_types: string[];
  extraction_failures: number;
}

export interface SourcesResponse {
  sources: SourceCoverage[];
  total_documents: number;
  total_properties: number;
  total_passages: number;
  retrieval_method: string;
  model: string;
  fallback_model: string;
  model_tested_on: string;
  coverage_gaps: string[];
  generated_at: string;
}

// ---- chat streaming events ----
export type StreamEvent =
  | {
      type: "evidence";
      items: EvidenceItem[];
      retrieval_method: string;
      applied_filters: Record<string, unknown>;
    }
  | { type: "delta"; text: string }
  | { type: "cards"; properties: Property[] }
  | {
      type: "done";
      citations: string[];
      property_ids: string[];
      model: string | null;
      finish_reason: string | null;
      request_id: string | null;
    }
  | {
      type: "error";
      category:
        | "provider_unavailable"
        | "quota_exhausted"
        | "timeout"
        | "bad_request"
        | "internal"
        | "rate_limited";
      message: string;
      request_id: string | null;
    };

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  evidence?: EvidenceItem[];
  cards?: Property[];
  citations?: string[];
  appliedFilters?: Record<string, unknown>;
  error?: { category: string; message: string };
  model?: string | null;
  pending?: boolean;
}

export interface Conversation {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  messages: ChatMessage[];
}
