export type DirectionSource = "RULE" | "LLM" | "USER";
export type DirectionStatus = "CONFIDENT" | "UNCERTAIN" | "UNKNOWN";

export interface DirectionLabel {
  code: string;
  label: string;
  confidence: number;
  source: DirectionSource;
  evidence: string[];
  is_primary: boolean;
}

export interface LeadershipLabel {
  code: string;
  label: string;
  confidence: number;
  source: DirectionSource;
  evidence: string[];
}

export interface BusinessDomainLabel {
  code: string;
  label: string;
  confidence: number;
  source: DirectionSource;
  evidence: string[];
}

export interface DirectionProfile {
  taxonomy_version: string;
  classifier_version: string;
  status: DirectionStatus;
  role_families: DirectionLabel[];
  leadership: LeadershipLabel | null;
  business_domains: BusinessDomainLabel[];
  specialties: string[];
}

export interface DirectionTaxonomyRoleFamily {
  code: string;
  label: string;
  aliases: string[];
}

export interface DirectionTaxonomy {
  taxonomy_version: string;
  role_families: DirectionTaxonomyRoleFamily[];
  leadership: Record<string, string>;
  business_domains: Record<string, string>;
}

export interface DirectionProfileResponse {
  direction_profile: DirectionProfile;
  profile_version: string;
  correction_id: string | null;
}

export interface DirectionProfileDetailResponse {
  direction_profile: DirectionProfile;
  effective_profile: DirectionProfile;
  machine_profile: DirectionProfile;
  manual_profile: DirectionProfile | null;
  profile_version: string;
  latest_active_correction_id: string | null;
  has_manual_override: boolean;
  sync_status?: string;
  scoring_impact?: { weight: number; description: string };
}

export interface DirectionEvaluationResponse {
  machine_profile: DirectionProfile;
  manual_profile: DirectionProfile | null;
  effective_profile: DirectionProfile;
  profile_version: string;
}
