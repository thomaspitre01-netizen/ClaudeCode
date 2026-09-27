-- Japan real-estate research database.
--
-- Three layers, so nothing a source said is ever lost:
--   listings        one row per advertisement (a URL on one source). Structured
--                   fields, the original Japanese, the English, and every raw
--                   label/value pair the page carried (raw_fields_json).
--   properties      one row per physical property. Several listings (the same
--                   house on SUUMO, athome and the agency's own site) point at
--                   one property after duplicate detection.
--   history tables  price_history and listing_events record every change, so
--                   "first seen at 58M, cut to 52M, gone in June" can be read back.
--
-- All money is integer JPY. All areas are m². Dates are ISO-8601 UTC strings.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sources (
    id                TEXT PRIMARY KEY,          -- 'suumo', 'athome', ...
    name              TEXT NOT NULL,
    base_url          TEXT NOT NULL,
    kind              TEXT NOT NULL,             -- portal | agency | specialist | marketplace | public
    policy            TEXT NOT NULL,             -- see sources/__init__.py POLICIES
    policy_notes      TEXT,
    enabled           INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS properties (
    id                INTEGER PRIMARY KEY,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    -- Renovation is an attribute to plan with, not a penalty. Filled by hand for now.
    renovation_low_jpy   INTEGER,
    renovation_high_jpy  INTEGER,
    renovation_notes     TEXT,
    notes             TEXT
);

CREATE TABLE IF NOT EXISTS listings (
    id                INTEGER PRIMARY KEY,
    source_id         TEXT NOT NULL REFERENCES sources(id),
    source_listing_id TEXT,                      -- the source's own id (nc_123, b-456...)
    url               TEXT NOT NULL UNIQUE,
    property_id       INTEGER REFERENCES properties(id),

    status            TEXT NOT NULL DEFAULT 'active',   -- active | removed
    first_seen        TEXT NOT NULL,             -- first time any crawl saw it
    last_seen         TEXT NOT NULL,             -- last time a crawl saw it listed
    last_fetched      TEXT,                      -- last time the detail page was parsed
    missed_runs       INTEGER NOT NULL DEFAULT 0,

    -- basic
    title_ja          TEXT,
    title_en          TEXT,
    agency_name       TEXT,
    agency_license    TEXT,                      -- 宅建業免許番号
    agency_phone      TEXT,
    address_ja        TEXT,
    prefecture        TEXT,                      -- English: Tokyo, Kanagawa
    municipality      TEXT,                      -- English: Musashino, Kamakura
    municipality_ja   TEXT,
    neighborhood_ja   TEXT,                      -- 吉祥寺本町2丁目
    lat               REAL,
    lng               REAL,
    geocode_source    TEXT,                      -- page | gsi
    geocode_precision TEXT,                      -- exact | chome | town | city
    in_scope          INTEGER NOT NULL DEFAULT 1,  -- inside target areas and <= price cap

    -- financial
    price_jpy         INTEGER,
    price_note_ja     TEXT,                      -- ranges, 応談, tax notes
    management_fee_jpy INTEGER,                  -- condos: 管理費 / month
    repair_reserve_jpy INTEGER,                  -- condos: 修繕積立金 / month
    other_costs_ja    TEXT,

    -- land
    land_area_m2      REAL,
    land_area_note_ja TEXT,                      -- 公簿 / 実測 / 私道負担
    plot_shape_ja     TEXT,
    frontage_m        REAL,
    road_access_ja    TEXT,                      -- 接道状況, verbatim
    road_width_m      REAL,
    building_coverage_pct REAL,                  -- 建ぺい率
    floor_area_ratio_pct  REAL,                  -- 容積率
    zoning_ja         TEXT,
    zoning            TEXT,                      -- English
    urbanization_control INTEGER,                -- 市街化調整区域: building may be restricted
    land_rights_ja    TEXT,
    land_rights       TEXT,                      -- freehold | leasehold | fixed_term_leasehold | other
    is_freehold       INTEGER,
    rebuild_prohibited INTEGER,                  -- 再建築不可
    setback_required  INTEGER,                   -- セットバック要
    restrictions_ja   TEXT,                      -- 法令上の制限 etc., verbatim

    -- building
    building_area_m2  REAL,
    floors_above      INTEGER,
    floors_below      INTEGER,
    year_built        INTEGER,
    month_built       INTEGER,
    structure_ja      TEXT,
    structure         TEXT,                      -- wood | steel | light_steel | rc | src | block | other
    layout_ja         TEXT,                      -- 5LDK
    rooms             INTEGER,
    bathrooms         INTEGER,
    kitchens          INTEGER,
    condition         TEXT,                      -- move_in_ready | minor_renovation | major_renovation
                                                 -- | full_renovation | derelict_rebuild | unknown
    condition_evidence TEXT,                     -- the Japanese words that set it
    earthquake_standard TEXT,                    -- new (post-1981) | old | unknown
    occupancy         TEXT,                      -- vacant | owner_occupied | tenanted | unknown
    handover_ja       TEXT,

    -- classification
    property_type     TEXT,                      -- controlled taxonomy, see normalize.PROPERTY_TYPES
    property_type_ja  TEXT,
    property_type_evidence TEXT,

    -- text
    description_ja    TEXT,
    description_en    TEXT,
    translated_by     TEXT,                      -- glossary | model id
    translated_at     TEXT,

    thumbnail_url     TEXT,
    image_urls_json   TEXT,
    raw_fields_json   TEXT,                      -- every label -> value pair on the page, Japanese
    content_hash      TEXT                       -- detects changed pages cheaply
);
CREATE INDEX IF NOT EXISTS ix_listings_property ON listings(property_id);
CREATE INDEX IF NOT EXISTS ix_listings_muni     ON listings(municipality);
CREATE INDEX IF NOT EXISTS ix_listings_source   ON listings(source_id, status);

CREATE TABLE IF NOT EXISTS listing_stations (
    listing_id   INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    line_ja      TEXT,
    line_en      TEXT,
    station_ja   TEXT,
    station_en   TEXT,
    walk_min     INTEGER,
    bus_min      INTEGER,
    raw_ja       TEXT
);
CREATE INDEX IF NOT EXISTS ix_stations_listing ON listing_stations(listing_id);

CREATE TABLE IF NOT EXISTS price_history (
    id           INTEGER PRIMARY KEY,
    listing_id   INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    observed_at  TEXT NOT NULL,
    price_jpy    INTEGER,
    previous_price_jpy INTEGER
);
CREATE INDEX IF NOT EXISTS ix_price_listing ON price_history(listing_id);

-- new | price_change | removed | relisted | agency_change | property_merged
CREATE TABLE IF NOT EXISTS listing_events (
    id           INTEGER PRIMARY KEY,
    listing_id   INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    observed_at  TEXT NOT NULL,
    event_type   TEXT NOT NULL,
    detail_json  TEXT
);
CREATE INDEX IF NOT EXISTS ix_events_time ON listing_events(observed_at);

CREATE TABLE IF NOT EXISTS snapshots (
    id           INTEGER PRIMARY KEY,
    listing_id   INTEGER REFERENCES listings(id) ON DELETE CASCADE,
    url          TEXT NOT NULL,
    fetched_at   TEXT NOT NULL,
    http_status  INTEGER,
    content_hash TEXT,
    raw_path     TEXT                            -- gzipped HTML under data/raw/
);

CREATE TABLE IF NOT EXISTS crawl_runs (
    id           INTEGER PRIMARY KEY,
    source_id    TEXT NOT NULL,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    complete     INTEGER NOT NULL DEFAULT 0,     -- only complete runs may mark listings removed
    pages        INTEGER NOT NULL DEFAULT 0,
    listings_seen INTEGER NOT NULL DEFAULT 0,
    new_listings INTEGER NOT NULL DEFAULT 0,
    price_changes INTEGER NOT NULL DEFAULT 0,
    robots_blocked INTEGER NOT NULL DEFAULT 0,
    errors       INTEGER NOT NULL DEFAULT 0,
    notes        TEXT
);

CREATE TABLE IF NOT EXISTS dedup_matches (
    listing_a    INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    listing_b    INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    score        REAL NOT NULL,
    reasons_json TEXT NOT NULL,
    decision     TEXT NOT NULL DEFAULT 'auto',   -- auto | confirmed | rejected (rejected is never re-merged)
    PRIMARY KEY (listing_a, listing_b)
);

CREATE TABLE IF NOT EXISTS favorites (
    property_id  INTEGER PRIMARY KEY REFERENCES properties(id) ON DELETE CASCADE,
    added_at     TEXT NOT NULL,
    note         TEXT
);

CREATE TABLE IF NOT EXISTS geocode_cache (
    query        TEXT PRIMARY KEY,
    lat          REAL,
    lng          REAL,
    matched      TEXT,
    fetched_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS translation_cache (
    text_hash    TEXT PRIMARY KEY,
    text_en      TEXT NOT NULL,
    model        TEXT NOT NULL,
    created_at   TEXT NOT NULL
);

-- One row per physical property with the numbers a dashboard filters on.
-- Values come from the property's most recently seen listing; price is the lowest
-- asking price among its active listings (agencies sometimes lag a price cut).
DROP VIEW IF EXISTS v_properties;
CREATE VIEW v_properties AS
WITH ranked AS (
    SELECT l.*, ROW_NUMBER() OVER (PARTITION BY l.property_id
                                   ORDER BY (l.status = 'active') DESC, l.last_seen DESC, l.id) AS rn
    FROM listings l WHERE l.property_id IS NOT NULL
),
agg AS (
    SELECT property_id,
           MIN(CASE WHEN status = 'active' THEN price_jpy END) AS active_price,
           MIN(first_seen) AS first_seen,
           MAX(last_seen)  AS last_seen,
           MAX(status = 'active') AS any_active,
           COUNT(*) AS listing_count,
           COUNT(DISTINCT source_id) AS source_count,
           GROUP_CONCAT(DISTINCT source_id) AS sources
    FROM listings WHERE property_id IS NOT NULL GROUP BY property_id
),
stn AS (
    SELECT s.listing_id, MIN(s.walk_min) AS walk_min
    FROM listing_stations s WHERE s.walk_min IS NOT NULL GROUP BY s.listing_id
),
first_price AS (
    SELECT l.property_id, ph.price_jpy AS initial_price,
           ROW_NUMBER() OVER (PARTITION BY l.property_id ORDER BY ph.observed_at, ph.id) AS rn
    FROM price_history ph JOIN listings l ON l.id = ph.listing_id
    WHERE ph.price_jpy IS NOT NULL
)
SELECT
    p.id                                   AS property_id,
    CASE WHEN a.any_active THEN 'active' ELSE 'removed' END AS status,
    r.property_type, r.title_ja, r.title_en,
    r.prefecture, r.municipality, r.municipality_ja, r.neighborhood_ja, r.address_ja,
    r.lat, r.lng,
    COALESCE(a.active_price, r.price_jpy)  AS price_jpy,
    fp.initial_price                       AS initial_price_jpy,
    r.land_area_m2, r.building_area_m2, r.year_built,
    CAST(strftime('%Y', 'now') AS INTEGER) - r.year_built AS building_age,
    r.layout_ja, r.rooms, r.structure, r.floors_above,
    r.zoning, r.building_coverage_pct, r.floor_area_ratio_pct, r.road_width_m,
    r.land_rights, r.is_freehold, r.rebuild_prohibited, r.urbanization_control,
    r.condition, r.condition_evidence, r.earthquake_standard, r.occupancy,
    stn.walk_min                           AS station_walk_min,
    (SELECT s.line_en || ' / ' || COALESCE(s.station_en, s.station_ja)
       FROM listing_stations s WHERE s.listing_id = r.id
       ORDER BY s.walk_min IS NULL, s.walk_min LIMIT 1) AS nearest_station,
    CASE WHEN r.land_area_m2 > 0 THEN ROUND(COALESCE(a.active_price, r.price_jpy) / r.land_area_m2) END
                                           AS price_per_m2_land,
    CASE WHEN r.building_area_m2 > 0 THEN ROUND(COALESCE(a.active_price, r.price_jpy) / r.building_area_m2) END
                                           AS price_per_m2_building,
    CASE WHEN r.building_area_m2 > 0 THEN ROUND(r.land_area_m2 / r.building_area_m2, 2) END
                                           AS land_to_building_ratio,
    -- Rough buyer-side costs: brokerage (3% + 60k, +10% tax) plus ~4% for registration,
    -- acquisition tax, stamp duty and judicial scrivener. An estimate, not a quote.
    CASE WHEN COALESCE(a.active_price, r.price_jpy) IS NOT NULL THEN
        CAST(COALESCE(a.active_price, r.price_jpy) * 1.04
             + (COALESCE(a.active_price, r.price_jpy) * 0.03 + 60000) * 1.1 AS INTEGER) END
                                           AS est_acquisition_cost_jpy,
    p.renovation_low_jpy, p.renovation_high_jpy, p.renovation_notes,
    a.first_seen, a.last_seen, a.listing_count, a.source_count, a.sources,
    r.url                                  AS primary_url,
    r.agency_name, r.thumbnail_url,
    (f.property_id IS NOT NULL)            AS is_favorite,
    r.in_scope
FROM properties p
JOIN ranked r ON r.property_id = p.id AND r.rn = 1
JOIN agg a    ON a.property_id = p.id
LEFT JOIN stn ON stn.listing_id = r.id
LEFT JOIN first_price fp ON fp.property_id = p.id AND fp.rn = 1
LEFT JOIN favorites f ON f.property_id = p.id;
