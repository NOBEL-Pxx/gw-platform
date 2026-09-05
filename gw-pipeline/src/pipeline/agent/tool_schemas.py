"""JSON Schema definitions for all Agent tools (OpenAI/DeepSeek function-calling format).

Each tool schema includes:
  - name: unique tool identifier
  - description: what the tool does (helps the model decide when to call it)
  - parameters: JSON Schema for arguments
"""

# ═══════════════════════════════════════════════════════════════════════════
# Database Query Tools
# ═══════════════════════════════════════════════════════════════════════════

SEARCH_OBSERVATIONS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "search_observations",
        "description": "Search gravitational wave observations by sky coordinates (RA/Dec), telescope/survey name, or UUID. Returns paginated FITS observation records from DSS2, NVSS, FIRST, WISE, ZTF, LEGACY, AliCPT surveys. Use this to find what data is available for a sky region.",
        "parameters": {
            "type": "object",
            "properties": {
                "ra": {"type": "number", "minimum": 0, "maximum": 360, "description": "Right Ascension in degrees (0-360). Optional."},
                "dec": {"type": "number", "minimum": -90, "maximum": 90, "description": "Declination in degrees (-90 to +90). Optional."},
                "radius": {"type": "number", "minimum": 0, "maximum": 180, "description": "Search cone radius in degrees (0-180, default 1.0).", "default": 1.0},
                "telescope": {"type": "string", "description": "Telescope/survey name filter (e.g. DSS2, NVSS, FIRST, WISE, ZTF, LEGACY, AliCPT). Optional."},
                "page": {"type": "integer", "minimum": 1, "description": "Page number (starting from 1).", "default": 1},
                "page_size": {"type": "integer", "minimum": 1, "maximum": 100, "description": "Results per page (1-100, default 10).", "default": 10},
            },
            "required": []
        }
    }
}

GET_ERROR_REPORTS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_error_reports",
        "description": "Get paginated anomaly detection error reports. Shows detected anomalies with telescope, band, coordinates, and FOV information. Use this to find problematic observations or survey data quality issues.",
        "parameters": {
            "type": "object",
            "properties": {
                "page": {"type": "integer", "minimum": 1, "description": "Page number (starting from 1).", "default": 1},
                "page_size": {"type": "integer", "minimum": 1, "maximum": 100, "description": "Results per page (1-100, default 10).", "default": 10},
            },
            "required": []
        }
    }
}

GET_ERROR_DETAIL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_error_detail",
        "description": "Get detailed information for a specific anomaly by error_id. Includes log content, anomaly type (spike/dip/pattern_break/wcs_mismatch), and list of affected data points with UUIDs. Use this to investigate a specific anomaly report.",
        "parameters": {
            "type": "object",
            "properties": {
                "error_id": {"type": "string", "description": "The error/anomaly ID to get details for."},
                "page": {"type": "integer", "description": "Page number for detail items.", "default": 1},
                "page_size": {"type": "integer", "description": "Results per page.", "default": 10},
            },
            "required": ["error_id"]
        }
    }
}

GET_ERROR_REFERENCE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_error_reference",
        "description": "Get multi-band observation data for a specific anomaly source. Returns FITS paths, images, and metadata across bands for a specific error_id + uuid combination. Use this to see all available band data for one anomaly data point.",
        "parameters": {
            "type": "object",
            "properties": {
                "error_id": {"type": "string", "description": "The error/anomaly ID."},
                "uuid": {"type": "string", "description": "The UUID of the specific data point within the error report."},
            },
            "required": ["error_id", "uuid"]
        }
    }
}

GET_COMMENTS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_comments",
        "description": "Get user comments for a gravitational wave observation record (grawave_id). Returns comments with user IDs, categories (analysis/crossmatch/verification/recommendation), and timestamps. Use this to see what researchers have noted about an observation.",
        "parameters": {
            "type": "object",
            "properties": {
                "grawave_id": {"type": "string", "description": "The gravitational wave observation ID to fetch comments for."},
                "page": {"type": "integer", "description": "Page number.", "default": 1},
                "page_size": {"type": "integer", "description": "Results per page.", "default": 10},
            },
            "required": ["grawave_id"]
        }
    }
}

COUNT_OBSERVATIONS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "count_observations",
        "description": "Count how many observations exist, optionally filtered by telescope/survey. Returns total count and breakdown by survey. Use this to get an overview of data availability before running detailed queries.",
        "parameters": {
            "type": "object",
            "properties": {
                "telescope": {"type": "string", "description": "Optional telescope/survey filter."},
            },
            "required": []
        }
    }
}

# ═══════════════════════════════════════════════════════════════════════════
# File Analysis Tools
# ═══════════════════════════════════════════════════════════════════════════

LIST_FITS_FILES_SCHEMA = {
    "type": "function",
    "function": {
        "name": "list_fits_files",
        "description": "List FITS files available in the data directory, optionally filtered by survey/telescope name. Returns file paths, sizes, and last-modified timestamps. Use this to discover what FITS data is available for analysis.",
        "parameters": {
            "type": "object",
            "properties": {
                "survey": {"type": "string", "description": "Optional survey name filter (e.g. DSS2, NVSS, AliCPT)."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "description": "Max files to return (default 50, max 200).", "default": 50},
            },
            "required": []
        }
    }
}

GET_FITS_HEADER_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_fits_header",
        "description": "Read the FITS header from a file. Returns WCS coordinate information (CRVAL, CRPIX, CD matrix), image dimensions, pixel scale, observation date, telescope, and band/filter info. Use this to inspect a FITS file's metadata before deeper analysis.",
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "FITS filename or path relative to the data directory."},
            },
            "required": ["filename"]
        }
    }
}

GET_FITS_STATS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_fits_stats",
        "description": "Compute statistical summary of FITS image data: min, max, mean, median, std, pixel value percentiles (1st, 5th, 95th, 99th). Use this to understand image quality, detect saturation, or assess signal-to-noise before detailed analysis.",
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "FITS filename or path relative to the data directory."},
            },
            "required": ["filename"]
        }
    }
}

# ═══════════════════════════════════════════════════════════════════════════
# DL Inference Tools
# ═══════════════════════════════════════════════════════════════════════════

CLASSIFY_MORPHOLOGY_SCHEMA = {
    "type": "function",
    "function": {
        "name": "classify_galaxy_morphology",
        "description": "Classify galaxy morphology from a FITS file using the Zoobot ConvNeXt-Nano ONNX model. Returns morphology class (spiral/elliptical/edge-on/merger/irregular) with confidence scores per class. Use this to identify galaxy types in survey images.",
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "FITS filename to classify."},
            },
            "required": ["filename"]
        }
    }
}

CLASSIFY_SOURCE_TYPE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "classify_source_type",
        "description": "Classify astronomical source type (star/galaxy/quasar) from FITS photometric features using an ONNX MLP classifier. Returns source class with confidence and feature importance ranking. Use this to identify what kind of object is in a FITS image.",
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "FITS filename to classify."},
            },
            "required": ["filename"]
        }
    }
}

DETECT_ANOMALY_SCHEMA = {
    "type": "function",
    "function": {
        "name": "detect_anomaly_dl",
        "description": "Detect anomalies in a FITS image using a CNN autoencoder (independent deep learning detector). Returns anomaly score (z-score, >3 = strong anomaly), reconstruction error, and verdict (anomalous/suspicious/normal). Use this to check if a FITS image contains unusual patterns not caught by the rule-based classifier.",
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "FITS filename to analyze for anomalies."},
            },
            "required": ["filename"]
        }
    }
}

GET_DL_MODEL_STATUS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_dl_model_status",
        "description": "Get status of all deep learning models: ONNX availability, model names, types, load status, and file sizes. Use this before running DL inference to verify models are loaded and ready.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    }
}

# ═══════════════════════════════════════════════════════════════════════════
# System & Pipeline Tools
# ═══════════════════════════════════════════════════════════════════════════

GET_SYSTEM_STATUS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_system_status",
        "description": "Get overall platform health status: backend connectivity, database status, degradation alerts, data source breakdown (live/fallback/mock/error counts), and service versions. Use this to check if the platform is operating normally before making scientific claims.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    }
}

GET_PIPELINE_INFO_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_pipeline_info",
        "description": "Get information about available science pipelines: WCS coordinate queries, source detection (DAOStarFinder), photometry (aperture), and FITS cutout services. Returns available endpoints with descriptions. Use this to discover what analysis capabilities are available.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    }
}

RUN_WCS_QUERY_SCHEMA = {
    "type": "function",
    "function": {
        "name": "run_wcs_query",
        "description": "Query the WCS (World Coordinate System) solution for a FITS file. Returns the sky coordinates (RA/Dec) for specified pixel positions, or the full WCS solution. Use this to convert between pixel and sky coordinates.",
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "FITS filename to query WCS for."},
                "x": {"type": "number", "minimum": 0, "description": "Pixel X coordinate (optional, non-negative)."},
                "y": {"type": "number", "minimum": 0, "description": "Pixel Y coordinate (optional, non-negative)."},
            },
            "required": ["filename"]
        }
    }
}

GET_API_DOCS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_api_docs",
        "description": "Get a summary of all available API endpoints on the platform. Returns endpoint paths, HTTP methods, and descriptions. Use this to discover what operations are possible on the platform.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    }
}

# ═══════════════════════════════════════════════════════════════════════════
# Master tool list (all tools available to the Agent)
# ═══════════════════════════════════════════════════════════════════════════

ALL_TOOL_SCHEMAS = [
    # Database queries
    SEARCH_OBSERVATIONS_SCHEMA,
    GET_ERROR_REPORTS_SCHEMA,
    GET_ERROR_DETAIL_SCHEMA,
    GET_ERROR_REFERENCE_SCHEMA,
    GET_COMMENTS_SCHEMA,
    COUNT_OBSERVATIONS_SCHEMA,
    # File analysis
    LIST_FITS_FILES_SCHEMA,
    GET_FITS_HEADER_SCHEMA,
    GET_FITS_STATS_SCHEMA,
    # DL inference
    CLASSIFY_MORPHOLOGY_SCHEMA,
    CLASSIFY_SOURCE_TYPE_SCHEMA,
    DETECT_ANOMALY_SCHEMA,
    GET_DL_MODEL_STATUS_SCHEMA,
    # System
    GET_SYSTEM_STATUS_SCHEMA,
    GET_PIPELINE_INFO_SCHEMA,
    RUN_WCS_QUERY_SCHEMA,
    GET_API_DOCS_SCHEMA,
]
