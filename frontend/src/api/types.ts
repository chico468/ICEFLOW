/**
 * TypeScript shapes for the ICEFLOW API.
 *
 * Every interface here was derived from an actual response of the running FastAPI service
 * (http://127.0.0.1:8000/openapi.json plus live probes of each endpoint), not from prose.
 * Where the build specification and the running service disagreed, the service won.
 */

// ---------------------------------------------------------------------------- provenance

/** Every response that carries modelled environmental data labels itself. Principle P2. */
export interface Provenance {
  kind: 'observed' | 'real_forecast' | 'simulated' | 'experimental_ml' | 'real-seed';
  source: string;
  product?: string;
  /** UTC ISO-8601 timestamp the data is valid at. */
  valid_time?: string;
  /** Hours since valid_time; null when not applicable or unknown. */
  age_hours?: number | null;
}

export interface SyntheticFlagged {
  is_synthetic?: boolean;
  source?: string;
  provenance?: Provenance;
}

// ---------------------------------------------------------------------------- evidence scorecard

export interface ScorecardRow {
  task: 'sic' | 'iceberg';
  lead_days: number;
  domain: string;
  season: string;
  model: string;
  rmse?: number | null;
  error_km?: number | null;
  ci: [number, number];
  skill_vs_baseline: number | null;
  n: number;
}

export interface ScorecardPromoted {
  sic: Record<string, boolean>;
  iceberg: Record<string, boolean>;
}

export interface ScorecardCoverage {
  [leadDays: string]: { target: number; empirical: number };
}

export interface ScorecardResponse {
  generated_at: string;
  git_sha: string | null;
  data_source: 'real' | 'none';
  product: string | null;
  version: string | null;
  train_years: string | null;
  test_years: string | null;
  rows: ScorecardRow[];
  promoted: ScorecardPromoted;
  coverage: ScorecardCoverage;
  caveats: string[];
}

/** Resolved calendar time plus independent simulation/model-relative offsets. */
export interface EnvironmentTimeResolution {
  mode: 'active_voyage' | 'planning_forecast';
  status: 'resolved' | 'unavailable';
  target_time_utc: string | null;
  reference_time_utc: string | null;
  elapsed_sim_hours: number | null;
  lead_hours: number | null;
  model_departure_time_hours: number | null;
  tick_time_utc: string | null;
  reason: string | null;
}

export type EnvironmentLayerStatus =
  | 'ready'
  | 'stale'
  | 'unavailable'
  | 'outside_coverage'
  | 'unsupported_time'
  | 'error';

export interface EnvironmentLayerMetadata {
  key: string;
  status: EnvironmentLayerStatus;
  target_time_utc: string;
  source_valid_time_utc: string | null;
  source_valid_interval_start_utc: string | null;
  source_valid_interval_end_utc: string | null;
  observation_time_utc: string | null;
  retrieved_at_utc: string | null;
  classification: 'observation' | 'analysis' | 'forecast' | null;
  forecast_lead_hours: number | null;
  age_hours: number | null;
  offset_hours: number | null;
  product: string;
  dataset: string | null;
  layer: string | null;
  variable: string;
  units: string | null;
  standard_name: string | null;
  data_updated_at_utc: string | null;
  metadata_updated_at_utc: string | null;
  product_released_at_utc: string | null;
  source_crs: string | null;
  tile_matrix_set: string | null;
  coverage_bounds_wgs84?: { west: number; south: number; east: number; north: number } | null;
  coverage_bounds_reason?: string | null;
  style: string | null;
  tile_max_zoom: number | null;
  tile_template: string | null;
  render_quality_layer?: string | null;
  render_quality_style?: string | null;
  render_quality_valid_time_utc?: string | null;
  render_quality_tile_matrix_set?: string | null;
  render_quality_tile_max_zoom?: number | null;
  render_quality_tile_template?: string | null;
  render_quality_tile_dimensions?: Record<string, string>;
  render_quality_reason?: string | null;
  render_tile_template?: string | null;
  render_status?: 'ready' | 'unavailable' | null;
  render_reason?: string | null;
  tile_dimensions: Record<string, string>;
  attribution: string;
  provenance: string;
  reason: string | null;
}

export interface EnvironmentLayersResponse {
  target_time_utc: string;
  mode: 'active_voyage' | 'planning_forecast';
  time_resolution: EnvironmentTimeResolution;
  layers: Record<string, EnvironmentLayerMetadata>;
}

export interface EnvironmentLayersRequest {
  target_time_utc: string;
  mode: 'active_voyage' | 'planning_forecast';
  departure_iso?: string;
  sim_hours?: number;
  timestamp_iso?: string;
  planning_reference_iso?: string;
  lead_hours?: number;
  departure_time_hours?: number;
}

/** Iceberg drift uses its own catalogue-seed model clock, not voyage UTC. */
export interface IcebergTimeResolution {
  mode: 'active_voyage';
  status: 'resolved' | 'unavailable';
  target_model_hours: number | null;
  forecast_lead_hours: number | null;
  forcing_start_hours: number | null;
  reason: string | null;
}

// -------------------------------------------------------------------------------- health

export interface HealthResponse {
  status: string;
  system: string;
  version: string;
  problem_statement_id: string;
  organization: string;
  department: string;
  uptime_seconds: number;
  model_versions: Record<string, string>;
  data_provenance: Record<string, Provenance>;
  machine_learning: { available: boolean; reason?: string; models?: Record<string, unknown> };
  /** Cache warm-up progress. The server answers immediately; this reports what is still building. */
  warmup: { state: 'pending' | 'warming' | 'ready' | 'failed'; seconds: number; detail: string };
  /** Indian Antarctic programme context. Full detail at /api/v1/geo/programme. */
  programme: {
    name: string;
    nodal_agency: string;
    legal_framework: string;
    season_window: string;
    stations_served: string[];
    detail_url: string;
  };
  external_network_calls: boolean;
  api_keys_required: boolean;
}

// ----------------------------------------------------------------------------------- geo

export interface CoastlineFeature {
  type: 'Feature';
  properties: { kind: string; rank: number; points: number };
  geometry: { type: 'Polygon'; coordinates: number[][][] };
}

export interface CoastlineResponse {
  type: 'FeatureCollection';
  attribution: string;
  crs_note: string;
  features: CoastlineFeature[];
  stats: { polygons: number; vertices: number; northern_limit_lat: number; source: string };
  provenance: Provenance;
}

export interface Station {
  id: string;
  name: string;
  country: string;
  operator?: string;
  region?: string;
  latitude: number;
  longitude: number;
  established?: number;
  is_indian?: boolean;
  port_approach?: string;
  notes?: string;
  anchorage_lat: number;
  anchorage_lon: number;
  anchorage_adjusted?: boolean;
  station_is_inland?: boolean;
}

export interface Port {
  id: string;
  name: string;
  country: string;
  latitude: number;
  longitude: number;
  notes?: string;
  anchorage_lat: number;
  anchorage_lon: number;
}

export interface RouteLeg {
  id: string;
  label: string;
  origin: string;
  destination: string;
  typical_season: string;
}

export interface StationsResponse {
  stations: Station[];
  ports: Port[];
  legs: RouteLeg[];
  provenance: Provenance;
  note: string;
}

/** Ports and stations reduced to one shape for the origin/destination pickers. */
export interface Endpoint {
  id: string;
  name: string;
  kind: 'port' | 'station';
  lat: number;
  lon: number;
  anchorageLat: number;
  anchorageLon: number;
  country: string;
  isIndian: boolean;
  inland: boolean;
  note: string;
  portApproach: string;
}

// --------------------------------------------------------------------------- environment

export interface EnvSample extends SyntheticFlagged {
  lat: number;
  lon: number;
  valid_time_hours: number;
  u10: number;
  v10: number;
  wind_speed_ms: number;
  wind_dir_from_deg: number;
  wind_gust_ms: number;
  uo: number;
  vo: number;
  current_speed_ms: number;
  current_dir_to_deg: number;
  sst_c: number;
  t2m_c: number;
  msl_hpa: number;
  sig_wave_height_m: number;
  visibility_km: number;
  katabatic_component_ms: number;
}

// -------------------------------------------------------------------------------- sea ice

export interface IceField extends SyntheticFlagged {
  lats: number[];
  lons: number[];
  valid_time_hours: number;
  lead_hours: number;
  /** [lat][lon] indexed, 0 to 1. */
  concentration: number[][];
  thickness_m: number[][];
  compression_index: number[][];
  drift_u_ms: number[][];
  drift_v_ms: number[][];
  polynya: number[][];
  concentration_uncertainty: number;
  ice_edge_lat: number[];
}

export interface IceState extends SyntheticFlagged {
  lat: number;
  lon: number;
  valid_time_hours: number;
  lead_hours: number;
  concentration: number;
  concentration_tenths: number;
  thickness_m: number;
  ice_type: string;
  stage_of_development: string;
  drift_u_ms: number;
  drift_v_ms: number;
  drift_speed_ms: number;
  drift_dir_to_deg: number;
  divergence_per_s: number;
  compression_index: number;
  besetting_risk: string;
  ridging_factor: number;
  is_polynya: boolean;
  freezing_degree_days: number;
  concentration_uncertainty: number;
}

export interface IceEdgeResponse extends SyntheticFlagged {
  lons: number[];
  edge_lat: number[];
  valid_time_hours: number;
}

export interface ForecastSkillRow {
  lead_hours: number;
  n_samples: number;
  rmse: number;
  mae: number;
  bias: number;
  iiee_fraction: number;
  persistence_rmse: number;
  persistence_iiee_fraction: number;
  skill_score_vs_persistence: number;
  note: string;
}

export interface ForecastSkillResponse {
  rows: ForecastSkillRow[];
  is_synthetic: boolean;
  provenance: Provenance;
  metrics_note: string;
}

// -------------------------------------------------------------------------------- POLARIS

export type IceClassKey =
  | 'PC1' | 'PC2' | 'PC3' | 'PC4' | 'PC5' | 'PC6' | 'PC7'
  | 'IA_Super' | 'IA' | 'IB' | 'IC' | 'Not_Ice_Strengthened';

export interface RiskMatrixResponse {
  ice_types: string[];
  ice_type_bounds_m: Record<string, number | null>;
  rows: Record<string, Record<string, number>>;
  equivalences: Record<string, string>;
  thresholds: { normal_operation: number; prohibited_below: number };
  reference: string;
  is_synthetic: boolean;
  provenance: Provenance;
}

export interface ComponentContribution {
  ice_type: string;
  concentration_tenths: number;
  risk_value: number;
  contribution: number;
}

export interface POLARISAssessment {
  vessel_ice_class: string;
  evaluated_as: string;
  total_concentration_tenths: number;
  rio: number;
  status: string;
  is_operation_permitted: boolean;
  is_speed_restricted: boolean;
  max_recommended_speed_knots: number;
  advisory_notes: string;
  per_component_contributions: ComponentContribution[];
  decayed_ice_applied: boolean;
  reference: string;
}

// ------------------------------------------------------------------------------ vessels

export interface Vessel {
  key: string;
  name: string;
  display_name: string;
  ice_class: string;
  length_m: number;
  waterline_length_m: number;
  beam_m: number;
  draft_m: number;
  block_coefficient: number;
  stem_angle_deg: number;
  waterline_angle_deg: number;
  flare_angle_deg: number;
  hull_friction_coeff: number;
  propulsion_efficiency: number;
  sfoc_g_per_kwh: number;
  installed_power_kw: number;
  propeller_diameter_m: number;
  n_propellers: number;
  ducted_propeller: boolean;
}

export interface VesselsResponse {
  vessels: Vessel[];
  note: string;
}

// --------------------------------------------------------------------------- resistance

export interface ResistanceResult {
  velocity_knots: number;
  ice_thickness_m: number;
  ice_concentration: number;
  crushing_resistance_kn: number;
  bending_resistance_kn: number;
  submergence_resistance_kn: number;
  open_water_resistance_kn: number;
  ice_resistance_kn: number;
  total_resistance_kn: number;
  required_power_kw: number;
  fuel_burn_rate_kg_per_hour: number;
  fuel_per_nm_kg: number;
  co2_kg_per_hour: number;
  is_beset: boolean;
  terms: Record<string, number>;
}

export interface SpeedPowerSeries {
  ice_thickness_m: number;
  resistance_kn: number[];
  required_power_kw: number[];
  fuel_kg_per_hour: number[];
  co2_kg_per_hour: number[];
  within_installed_power: boolean[];
  attainable_speed_knots: number;
}

export interface SpeedPowerResponse {
  vessel: {
    name: string;
    display_name: string;
    ice_class: string;
    length_m: number;
    beam_m: number;
    draft_m: number;
    installed_power_kw: number;
    bollard_pull_kn: number;
  };
  ice_concentration: number;
  speeds_knots: number[];
  series: SpeedPowerSeries[];
  model: string;
  notes: string;
}

// ------------------------------------------------------------------------------ icebergs

export interface IcebergProfile {
  berg_id: string;
  latitude: number;
  longitude: number;
  length_m: number;
  width_m: number;
  sail_height_m: number;
  keel_depth_m: number;
  mass_metric_tonnes: number;
  origin: string;
  size_class: string;
  /** Present only when the catalogue was requested with lead_hours > 0. */
  forecast_latitude?: number;
  forecast_longitude?: number;
  forecast_lead_hours?: number;
  drift_km?: number;
  mass_lost_percent?: number;
}

export interface IcebergsResponse {
  icebergs: IcebergProfile[];
  count: number;
  exclusion_radius_nm: number;
  provenance: Provenance;
  time_alignment?: IcebergTimeResolution;
}

export interface TrajectoryPoint {
  hour: number;
  latitude: number;
  longitude: number;
  speed_knots: number;
  heading_deg: number;
  distance_from_origin_km: number;
  u_ms: number;
  v_ms: number;
  length_m: number;
  mass_metric_tonnes: number;
  size_class: string;
  uncertainty_radius_50_km: number;
  uncertainty_radius_90_km: number;
}

export interface ForceBudget {
  air_drag_mn: number;
  water_drag_mn: number;
  coriolis_mn: number;
  pressure_gradient_mn: number;
  wave_radiation_mn: number;
  response_timescale_hours: number;
}

export interface IcebergForecast extends SyntheticFlagged {
  berg_id: string;
  forecast_horizon_hours: number;
  trajectory: TrajectoryPoint[];
  net_displacement_km: number;
  mean_speed_knots: number;
  initial_size_class: string;
  final_size_class: string;
  mass_lost_percent: number;
  final_length_m: number;
  ensemble_members: number;
  force_budget: ForceBudget | null;
  integration_scheme: string;
}

export interface ClosestApproach {
  berg_id: string;
  distance_nm: number;
  time_hours: number;
  waypoint_index: number;
  berg_position: [number, number];
  route_position: [number, number];
  threat_level: string;
  advisory: string;
}

export interface IcebergRiskResponse {
  route_waypoints: number;
  approaches: ClosestApproach[];
  highest_threat: ClosestApproach | null;
}

// -------------------------------------------------------------------------------- radar

export interface RadarContact {
  contact_id: string;
  bearing_deg: number;
  relative_bearing_deg: number;
  range_nm: number;
  size_class: string;
  estimated_length_m: number;
  estimated_freeboard_m: number;
  radar_cross_section_m2: number;
  detection_confidence: number;
  signal_to_clutter_db: number;
  tcpa_minutes: number;
  cpa_nm: number;
  threat_level: string;
  is_true_target: boolean;
  latitude: number;
  longitude: number;
}

export interface RadarSweep extends SyntheticFlagged {
  contacts: RadarContact[];
  sea_clutter_level: number;
  detection_range_nm: number;
  sweep_time_hours: number;
  own_position: { lat: number; lon: number };
  own_heading_deg: number;
  own_speed_knots: number;
  false_alarm_count: number;
  estimated_missed_targets: number;
  missed_within_alert_range: number;
  true_target_count: number;
  detected_true_count: number;
  ice_concentration: number;
  ice_ridging_factor: number;
  sig_wave_height_m: number;
  wind_speed_ms: number;
  max_range_nm: number;
  antenna_rpm: number;
  band_ghz: number;
  seed: number;
}

// ------------------------------------------------------------------------------- routing

export interface RouteWeights {
  fuel: number;
  time: number;
  risk: number;
}

export interface Waypoint {
  latitude: number;
  longitude: number;
  speed_knots: number;
  ice_concentration: number;
  ice_thickness_m: number;
  rio_score: number;
  is_safe: boolean;
  segment_fuel_tonnes: number;
  cumulative_fuel_tonnes: number;
  cumulative_hours: number;
  ice_type: string;
  compression_index: number;
  besetting_risk: string;
  distance_from_start_nm: number;
  heading_deg: number;
  required_power_kw: number;
  coast_clearance_nm: number;
  wind_speed_ms: number;
  wave_height_m: number;
  polaris_speed_cap_knots: number;
  attainable_speed_knots: number;
}

export interface WaypointEta {
  index: number;
  eta_iso: string;
}

export interface RouteEvaluation {
  label: string;
  waypoints: Waypoint[];
  total_distance_nm: number;
  total_transit_hours: number;
  total_fuel_burn_tonnes: number;
  total_co2_tonnes: number;
  minimum_rio: number;
  mean_rio: number;
  max_compression_index: number;
  max_ice_thickness_m: number;
  is_feasible: boolean;
  infeasible_reason: string;
  prohibited_waypoints: number;
  // v1.1: clock times derived from the voyage departure.
  arrival_iso?: string;
  waypoint_etas?: WaypointEta[];
}

export interface SearchDiagnostics {
  nodes_expanded: number;
  nodes_rejected_land: number;
  nodes_rejected_rio: number;
  nodes_rejected_iceberg: number;
  nodes_rejected_clearance: number;
  search_ms: number;
  lattice_cells: number;
  forecast_slices: number;
  goal_reached: boolean;
}

export interface OptimizationSummary {
  origin: [number, number];
  destination: [number, number];
  total_distance_nm: number;
  total_transit_hours: number;
  total_fuel_burn_tonnes: number;
  baseline_direct_fuel_tonnes: number;
  fuel_saved_percentage: number;
  minimum_rio: number;
  waypoints_count: number;
  waypoints: Waypoint[];
  optimized: RouteEvaluation | null;
  baseline: RouteEvaluation | null;
  time_saved_hours: number;
  distance_delta_nm: number;
  co2_saved_tonnes: number;
  cost_saved_usd: number;
  cost_saved_inr: number;
  baseline_would_be_prohibited: boolean;
  vessel_name: string;
  ice_class: string;
  weights: RouteWeights | null;
  departure_time_hours: number;
  search: SearchDiagnostics | null;
  warnings: string[];
  savings_method: string;
  is_synthetic_environment: boolean;
  // v1.1: wall-clock departure and the environment that produced the data.
  departure_iso?: string;
  arrival_iso?: string;
  environment_mode?: string;
  provenance?: Record<string, string>;
}

export type RouteProfileId = 'safety-first' | 'balanced' | 'fuel-efficient' | 'fastest';

export interface RouteAlternative {
  id: RouteProfileId;
  name: string;
  description: string;
  weights: RouteWeights;
  evaluation: RouteEvaluation;
  is_feasible: boolean;
  goal_reached: boolean;
  warnings: string[];
  search: SearchDiagnostics;
  is_synthetic_environment: boolean;
}

export interface RouteAlternativesResponse {
  candidates: RouteAlternative[];
  balanced_summary: OptimizationSummary | null;
  comparison_reference_id: 'balanced';
  omitted_profiles: { profile_id: RouteProfileId; reason: string }[];
  distinct_alternatives_found: number;
  planning_ms: number;
  is_synthetic_environment: boolean;
  environment_provenance: Record<string, Provenance>;
}

export interface RouteRequest {
  start_lat?: number;
  start_lon?: number;
  dest_lat?: number;
  dest_lon?: number;
  ice_class?: IceClassKey;
  origin_id?: string;
  destination_id?: string;
  vessel_key?: string;
  weights?: RouteWeights;
  departure_time_hours?: number;
  planning_reference_iso?: string;
  lead_hours?: number;
  grid_resolution_deg?: number;
  avoid_icebergs?: boolean;
  // v1.1: wall-clock departure and the environment mode that produced the data.
  departure_iso?: string;
  environment_mode?: 'simulated' | 'real_ice' | 'replay';
  replay_date?: string;
}

// ------------------------------------------------------------------------------- voyage

export interface VoyageAlert {
  alert_id: string;
  tick: number;
  sim_hours: number;
  code: string;
  severity: 'INFO' | 'CAUTION' | 'WARNING' | 'CRITICAL' | string;
  message: string;
  advisory: string;
  latitude: number;
  longitude: number;
  cleared_at_tick: number | null;
}

export interface VoyageTick {
  tick: number;
  sim_hours: number;
  timestamp_iso: string;
  environment_time?: EnvironmentTimeResolution | null;
  latitude: number;
  longitude: number;
  heading_deg: number;
  speed_knots: number;
  speed_over_ground_knots: number;
  distance_travelled_nm: number;
  distance_remaining_nm: number;
  progress_percent: number;
  eta_hours: number;
  fuel_used_tonnes: number;
  fuel_rate_kg_per_hour: number;
  required_power_kw: number;
  power_utilisation_percent: number;
  co2_tonnes: number;
  ice_concentration: number;
  ice_thickness_m: number;
  ice_type: string;
  rio: number;
  rio_status: string;
  polaris_speed_cap_knots: number;
  attainable_speed_knots: number;
  compression_index: number;
  besetting_risk: string;
  wind_speed_ms: number;
  wind_dir_from_deg: number;
  wave_height_m: number;
  air_temp_c: number;
  sst_c: number;
  visibility_km: number;
  radar_contacts: number;
  radar_highest_threat: string;
  nearest_contact_nm: number | null;
  sea_clutter_level: number;
  active_alerts: string[];
  is_beset: boolean;
}

export type VoyageStatus = 'PLANNED' | 'UNDER_WAY' | 'ARRIVED' | 'BESET' | 'ABORTED' | string;

export interface VoyageState {
  voyage_id: string;
  status: VoyageStatus;
  created_iso: string;
  departure_iso: string;
  environment_time?: EnvironmentTimeResolution | null;
  model_departure_time_hours?: number;
  vessel_name: string;
  vessel_key: string;
  ice_class: string;
  route_profile_id: RouteProfileId;
  origin: [number, number];
  destination: [number, number];
  origin_name: string;
  destination_name: string;
  planned_route: Waypoint[];
  baseline_route: Waypoint[];
  travelled_track: [number, number][];
  ticks: VoyageTick[];
  alerts: VoyageAlert[];
  current_tick: number;
  sim_hours: number;
  total_fuel_tonnes: number;
  total_co2_tonnes: number;
  distance_travelled_nm: number;
  reroute_count: number;
  plan_summary: OptimizationSummary | null;
  is_synthetic_environment: boolean;
}

export interface CreateVoyageRequest {
  origin_id?: string;
  destination_id?: string;
  origin?: [number, number];
  destination?: [number, number];
  vessel_key?: string;
  ice_class?: IceClassKey;
  weights?: RouteWeights;
  route_profile_id?: RouteProfileId;
  departure_time_hours?: number;
  grid_resolution_deg?: number;
  avoid_icebergs?: boolean;
  departure_iso?: string;
}

// ---------------------------------------------------------------------- websocket frames

export type VoyageSocketFrame =
  | { type: 'state'; payload: VoyageState }
  | { type: 'tick'; payload: VoyageTick }
  | { type: 'alert'; payload: VoyageAlert }
  | { type: 'done'; payload: { status: VoyageStatus } }
  | { type: 'paused'; payload: { sim_hours: number } }
  | { type: 'reroute'; payload: OptimizationSummary }
  | { type: 'error'; payload: { message: string } };

export type VoyageSocketAction =
  | { action: 'start'; tick_hours: number; interval_ms: number }
  | { action: 'pause' }
  | { action: 'step'; tick_hours?: number }
  | { action: 'reroute' }
  | { action: 'close' };

// ----------------------------------------------------------------------------- telemetry

export interface BandwidthReport {
  domain: {
    lat_min: number;
    lat_max: number;
    lon_min: number;
    lon_max: number;
    resolution_deg: number;
    grid_cells: number;
  };
  full_raster_bytes: number;
  full_raster_gzip_bytes: number;
  contour_payload_bytes: number;
  contour_payload_gzip_bytes: number;
  delta_payload_gzip_bytes: number;
  updates_per_day: number;
  daily_total_bytes: number;
  daily_total_kb: number;
  budget_kb: number;
  within_budget: boolean;
  compression_ratio_vs_raster: number;
  contour_levels: number[];
  coordinate_decimals: number;
  method: string;
  link: string;
}


// ----------------------------------------------------------------- Stage A: flow, observed, regional

/**
 * Gridded wind and current from /env/field. Every grid is [lat][lon] with ascending axes.
 * `is_synthetic` is true for every field this service produces today, and the interface labels
 * the flow layers from it rather than from a hard-coded string.
 */
export interface EnvField extends SyntheticFlagged {
  lats: number[];
  lons: number[];
  valid_time_hours: number;
  u10: number[][];
  v10: number[][];
  wind_speed_ms: number[][];
  current_u: number[][];
  current_v: number[][];
  current_speed_ms: number[][];
  sig_wave_height_m: number[][];
}

/** Cached real geographic velocity grid. Missing source cells remain null and cannot advect particles. */
export interface RealFlowField {
  available: boolean;
  reason: string | null;
  provenance: {
    kind: 'wind' | 'current';
    source?: string;
    product?: string;
    dataset_id?: string;
    valid_time?: string;
    retrieved_at?: string;
    classification?: string;
    units: 'm/s';
    crs: 'EPSG:4326';
    coordinate_units: string;
    stale?: boolean;
    age_hours?: number;
    forecast_lead_hours?: number;
    native_resolution_deg?: number;
    cache_file?: string;
    acquisition_command: string;
    [key: string]: unknown;
  };
  lats?: number[];
  lons?: number[];
  u?: (number | null)[][];
  v?: (number | null)[][];
}

export interface ObservedIceberg {
  id: string;
  latitude: number;
  longitude: number;
  length_nm: number;
  width_nm: number;
  area_sqnm: number;
  area_sqkm: number;
  observed_date: string;
}

/** The observed iceberg snapshot. When `available` is false only `reason` and `setup` are meaningful. */
export interface ObservedIcebergsResponse {
  available: boolean;
  kind: 'observed';
  reason?: string;
  setup?: string;
  source?: string;
  file?: string;
  observed_date?: string;
  age_days?: number;
  stale?: boolean;
  stale_after_days?: number;
  stale_note?: string;
  position_uncertainty?: string;
  used_for_routing: boolean;
  count: number;
  rejected?: { id: string; reason: string }[];
  warnings?: string[];
  limitations?: string[];
  icebergs: ObservedIceberg[];
}

/** Flat [lon, lat, lon, lat, ...] rings; the first ring of a polygon is its exterior. */
export type FlatRing = number[];

export interface RegionalCountry {
  name: string;
  label: [number, number];
  label_rank: number;
  polygons: FlatRing[][];
}

export interface RegionalContext {
  available: boolean;
  reason?: string;
  setup?: string[];
  region: { lon_min: number; lon_max: number; lat_min: number; lat_max: number };
  attribution?: string;
  accuracy_note?: string;
  generated_utc?: string;
  sources?: { layer: string; dataset: string; source: string; sha256: string; retrieved_utc: string }[];
  land: FlatRing[][];
  countries: RegionalCountry[];
}
