#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-http://127.0.0.1:8000}"
FAILS=0

# Helper to extract body and status code from curl output
check_json() {
    local name="$1"
    local cmd="$2"
    local py_check="$3"
    local expect="$4"
    local out body http_code
    out=$(eval "$cmd" 2>/dev/null) || { echo "FAIL: $name (request failed)"; FAILS=$((FAILS+1)); return; }
    http_code=$(echo "$out" | tail -n 1)
    body=$(echo "$out" | sed '$d')
    
    # Pass body and http_code to python via environment
    if BODY="$body" HTTP_CODE="$http_code" python3 -c "
import sys, json, os
data = json.loads(os.environ['BODY'])
http_code = os.environ['HTTP_CODE']
try:
    $py_check
    sys.exit(0)
except Exception as e:
    sys.exit(1)
" 2>/dev/null; then
        echo "PASS: $name"
    else
        echo "FAIL: $name (expected: $expect)"
        FAILS=$((FAILS + 1))
    fi
}

# 1. coverage 200 with replay.start/end
check_json "coverage 200 with replay.start/end" \
    "curl -s -w '\n%{http_code}' $BASE_URL/api/v1/environment/coverage" \
    "data=data.get('replay',{}); assert data.get('start') and data.get('end')" \
    "replay.start and replay.end present"

# 2. ice field in replay mode for 2022-01-15: is_synthetic false, provenance kind observed, missing cells null never 0
check_json "route replay 2022-01-15 is_synthetic false" \
    "curl -s -w '\n%{http_code}' -X POST '$BASE_URL/api/v1/route/optimize' -H 'Content-Type: application/json' -d '{\"start_lat\":-60.0,\"start_lon\":48.0,\"dest_lat\":-59.0,\"dest_lon\":50.0,\"ice_class\":\"PC5\",\"environment_mode\":\"replay\",\"replay_date\":\"2022-01-15\",\"departure_iso\":\"2022-01-15T00:00:00+00:00\"}'" \
    "assert data.get('is_synthetic_environment') is False" \
    "is_synthetic_environment == false"

check_json "route replay 2022-01-15 provenance kind observed" \
    "curl -s -w '\n%{http_code}' -X POST '$BASE_URL/api/v1/route/optimize' -H 'Content-Type: application/json' -d '{\"start_lat\":-60.0,\"start_lon\":48.0,\"dest_lat\":-59.0,\"dest_lon\":50.0,\"ice_class\":\"PC5\",\"environment_mode\":\"replay\",\"replay_date\":\"2022-01-15\",\"departure_iso\":\"2022-01-15T00:00:00+00:00\"}'" \
    "assert any(p.get('kind')=='observed' for p in data.get('provenance',[]))" \
    "provenance kind observed present"

check_json "route replay ice_concentration valid (not null)" \
    "curl -s -w '\n%{http_code}' -X POST '$BASE_URL/api/v1/route/optimize' -H 'Content-Type: application/json' -d '{\"start_lat\":-60.0,\"start_lon\":48.0,\"dest_lat\":-59.0,\"dest_lon\":50.0,\"ice_class\":\"PC5\",\"environment_mode\":\"replay\",\"replay_date\":\"2022-01-15\",\"departure_iso\":\"2022-01-15T00:00:00+00:00\"}'" \
    "assert all(wp.get('ice_concentration') is not None for wp in data.get('waypoints',[]))" \
    "ice_concentration not null"

# 3. wind, wave and current layers in replay: is_synthetic false, kind simulated
check_json "wind layer replay kind simulated" \
    "curl -s -w '\n%{http_code}' -X POST '$BASE_URL/api/v1/route/optimize' -H 'Content-Type: application/json' -d '{\"start_lat\":-60.0,\"start_lon\":48.0,\"dest_lat\":-59.0,\"dest_lon\":50.0,\"ice_class\":\"PC5\",\"environment_mode\":\"replay\",\"replay_date\":\"2022-01-15\",\"departure_iso\":\"2022-01-15T00:00:00+00:00\"}'" \
    "assert any(p.get('layer')=='atmosphere_ocean' and p.get('kind')=='simulated' for p in data.get('provenance',[]))" \
    "wind kind simulated"

check_json "current layer replay kind simulated" \
    "curl -s -w '\n%{http_code}' -X POST '$BASE_URL/api/v1/route/optimize' -H 'Content-Type: application/json' -d '{\"start_lat\":-60.0,\"start_lon\":48.0,\"dest_lat\":-59.0,\"dest_lon\":50.0,\"ice_class\":\"PC5\",\"environment_mode\":\"replay\",\"replay_date\":\"2022-01-15\",\"departure_iso\":\"2022-01-15T00:00:00+00:00\"}'" \
    "assert any(p.get('layer')=='atmosphere_ocean' and p.get('kind')=='simulated' for p in data.get('provenance',[]))" \
    "current kind simulated"

check_json "waves present when ice_concentration < 0.15" \
    "curl -s -w '\n%{http_code}' -X POST '$BASE_URL/api/v1/route/optimize' -H 'Content-Type: application/json' -d '{\"start_lat\":-60.0,\"start_lon\":48.0,\"dest_lat\":-59.0,\"dest_lon\":50.0,\"ice_class\":\"PC5\",\"environment_mode\":\"replay\",\"replay_date\":\"2022-01-15\",\"departure_iso\":\"2022-01-15T00:00:00+00:00\"}'" \
    "assert all(wp.get('wave_height_m') is not None for wp in data.get('waypoints',[]) if wp.get('ice_concentration',1.0)<0.15)" \
    "waves present when ice_concentration < 0.15"

# 4. request outside coverage returns 422 with code out_of_coverage
check_json "route outside coverage returns 422 out_of_coverage" \
    "curl -s -w '\n%{http_code}' -X POST '$BASE_URL/api/v1/route/optimize' -H 'Content-Type: application/json' -d '{\"start_lat\":-60.0,\"start_lon\":48.0,\"dest_lat\":-59.0,\"dest_lon\":50.0,\"ice_class\":\"PC5\",\"environment_mode\":\"replay\",\"replay_date\":\"1990-01-15\",\"departure_iso\":\"2022-01-15T00:00:00+00:00\"}'" \
    "assert http_code=='422' and data.get('detail',{}).get('code')=='out_of_coverage'" \
    "422 with out_of_coverage"

# 5. forecast/sic - model not trained, returns 503
check_json "forecast/sic returns 503 when model unavailable" \
    "curl -s -w '\n%{http_code}' '$BASE_URL/api/v1/forecast/sic?issue_date=2022-01-15&lead_days=3'" \
    "assert http_code=='503' and 'unavailable' in data.get('detail','')" \
    "503 with unavailable"

# 6. forecast/sic/verify - model not trained, returns 503
check_json "forecast/sic/verify returns 503 when model unavailable" \
    "curl -s -w '\n%{http_code}' '$BASE_URL/api/v1/forecast/sic/verify?issue_date=2022-01-15&lead_days=3'" \
    "assert http_code=='503' and 'unavailable' in data.get('detail','')" \
    "503 with unavailable"

# 7. icebergs/forecast for a named observed berg
ICEBERG_ID=$(curl -s "$BASE_URL/api/v1/icebergs?mode=observed" | python3 -c "import sys, json; data=json.load(sys.stdin); bergs=[b['berg_id'] for b in data.get('icebergs',[])]; print(bergs[0] if bergs else '')" 2>/dev/null)
if [ -n "$ICEBERG_ID" ]; then
    check_json "icebergs/forecast returns response for available berg" \
        "curl -s -w '\n%{http_code}' '$BASE_URL/api/v1/icebergs/forecast?name=$ICEBERG_ID'" \
        "assert http_code=='200'" \
        "200 response"
else
    echo "SKIP: icebergs/forecast (no bergs available)"
fi

# 8. replay plan Cape Town -> Bharati 2022-01-15 (may take time)
check_json "replay plan Cape Town -> Bharati 2022-01-15" \
    "timeout 180 curl -s -w '\n%{http_code}' -X POST '$BASE_URL/api/v1/route/optimize' -H 'Content-Type: application/json' -d '{\"origin_id\":\"cape_town\",\"destination_id\":\"bharati\",\"environment_mode\":\"replay\",\"replay_date\":\"2022-01-15\",\"departure_iso\":\"2022-01-15T00:00:00+00:00\"}'" \
    "assert http_code=='200' and all(k in data for k in ('arrival_iso','waypoint_etas','waypoints_count')) and data.get('waypoints_count',0)>=2" \
    "200 with arrival_iso, waypoint_etas, >=2 points"

# 9. voyage start from that route, ticks and timeline with at least 100 steps
VOYAGE_ID=$(curl -s -X POST "$BASE_URL/api/v1/voyage" -H 'Content-Type: application/json' -d '{"origin_id":"cape_town","destination_id":"bharati","vessel_key":"vasiliy_golovnin","environment_mode":"replay","replay_date":"2022-01-15","departure_iso":"2022-01-15T00:00:00+00:00"}' 2>/dev/null | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('voyage_id',''))" 2>/dev/null || echo "")

if [ -n "$VOYAGE_ID" ]; then
    check_json "voyage start from replay route" \
        "curl -s -w '\n%{http_code}' -X POST '$BASE_URL/api/v1/voyage' -H 'Content-Type: application/json' -d '{\"origin_id\":\"cape_town\",\"destination_id\":\"bharati\",\"vessel_key\":\"vasiliy_golovnin\",\"environment_mode\":\"replay\",\"replay_date\":\"2022-01-15\",\"departure_iso\":\"2022-01-15T00:00:00+00:00\"}'" \
        "assert http_code=='200' and 'voyage_id' in data" \
        "200 with voyage_id"
    
    # Step voyage to generate ticks
    for i in {1..20}; do
        curl -s -X POST "$BASE_URL/api/v1/voyage/$VOYAGE_ID/step" -H 'Content-Type: application/json' -d '{}' >/dev/null 2>&1
    done
    
    check_json "voyage step" \
        "curl -s -w '\n%{http_code}' -X POST '$BASE_URL/api/v1/voyage/$VOYAGE_ID/step' -H 'Content-Type: application/json' -d '{}'" \
        "assert http_code=='200' and 'ticks_produced' in data" \
        "200 with ticks_produced"
    
    check_json "voyage timeline >=100 steps" \
        "curl -s -w '\n%{http_code}' '$BASE_URL/api/v1/voyage/$VOYAGE_ID/timeline'" \
        "assert http_code=='200' and len(data.get('steps',[]))>=100" \
        "200 with >=100 steps"
else
    echo "FAIL: voyage start (no voyage_id)"
    FAILS=$((FAILS + 1))
fi

# 10. scorecard: every row has domain/season/sector (as evaluation_scope) and n, no row has ci [null, null], promoted values have the {promoted, model} shape
check_json "scorecard rows have domain/season/sector and n" \
    "curl -s -w '\n%{http_code}' '$BASE_URL/api/v1/evidence/scorecard'" \
    "assert http_code=='200' and all('domain' in r and 'season' in r and 'sector' in r and 'n' in r for r in data.get('rows',[]))" \
    "domain, season, sector and n present in all rows"

check_json "scorecard no row has ci [null, null]" \
    "curl -s -w '\n%{http_code}' '$BASE_URL/api/v1/evidence/scorecard'" \
    "assert http_code=='200' and not any(r.get('ci')==[None,None] for r in data.get('rows',[]))" \
    "no ci [null, null]"

check_json "scorecard promoted values have {promoted, model} shape" \
    "curl -s -w '\n%{http_code}' '$BASE_URL/api/v1/evidence/scorecard'" \
    "assert http_code=='200' and all(isinstance(v,dict) and 'promoted' in v and 'model' in v for v in data.get('promoted',{}).get('sic',{}).values())" \
    "promoted {promoted, model} shape"

if [ $FAILS -eq 0 ]; then
    echo "ALL CHECKS PASSED"
    exit 0
else
    echo "TOTAL FAILS: $FAILS"
    exit 1
fi
