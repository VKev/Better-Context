"""Better Context: AI Agent Codebase Intelligence CLI.

A CLI tool that programmatically processes codebases, breaking them into
mathematically structured, semantically meaningful pieces that AI agents
can progressively consume.
"""

__version__ = "1.0.0"

# Re-export key types for convenient access
from better_context.config import Config, load_config, validate_config
from better_context.manifest import (
    MANIFEST_VERSION,
    Manifest,
    ManifestMeta,
    FileEntry,
    ChunkEntry,
    ImportEntry,
    ExportEntry,
    GraphData,
    ParseError as ManifestParseError,
    ManifestDiff,
    create_manifest_meta,
    save_manifest,
    load_manifest,
    validate_manifest,
    diff_manifests,
)
from better_context.errors import (
    AnalysisErrors,
    AnalysisWarning,
    FileError,
    BetterContextError,
    ConfigurationError,
    ManifestError,
    ParseError,
    ResolutionError,
    read_file_with_fallback,
    format_error_report,
    get_exit_code,
)
# Phase 4: Advanced Analysis exports
from better_context.coupling import (
    CouplingMetrics,
    ZoneReport,
    calculate_coupling_metrics,
    calculate_all_coupling_metrics,
    calculate_directory_metrics,
    generate_zone_report,
    identify_critical_modules,
    get_coupling_summary,
)
from better_context.architecture import (
    LayerClassification,
    LayerViolation,
    ArchitectureReport,
    classify_all_files,
    detect_layer_violations,
    analyze_architecture,
)
from better_context.callgraph import (
    CallSite,
    CallGraph,
    build_call_graph,
    get_callers,
    get_callees,
    get_call_graph_stats,
)

__all__ = [
    "__version__",
    # Config
    "Config",
    "load_config",
    "validate_config",
    # Manifest types
    "MANIFEST_VERSION",
    "Manifest",
    "ManifestMeta",
    "FileEntry",
    "ChunkEntry",
    "ImportEntry",
    "ExportEntry",
    "GraphData",
    "ManifestParseError",
    "ManifestDiff",
    "create_manifest_meta",
    "save_manifest",
    "load_manifest",
    "validate_manifest",
    "diff_manifests",
    # Error handling
    "AnalysisErrors",
    "AnalysisWarning",
    "FileError",
    "BetterContextError",
    "ConfigurationError",
    "ManifestError",
    "ParseError",
    "ResolutionError",
    "read_file_with_fallback",
    "format_error_report",
    "get_exit_code",
    # Phase 4: Coupling metrics
    "CouplingMetrics",
    "ZoneReport",
    "calculate_coupling_metrics",
    "calculate_all_coupling_metrics",
    "calculate_directory_metrics",
    "generate_zone_report",
    "identify_critical_modules",
    "get_coupling_summary",
    # Phase 4: Architecture detection
    "LayerClassification",
    "LayerViolation",
    "ArchitectureReport",
    "classify_all_files",
    "detect_layer_violations",
    "analyze_architecture",
    # Phase 4: Call graph
    "CallSite",
    "CallGraph",
    "build_call_graph",
    "get_callers",
    "get_callees",
    "get_call_graph_stats",
]
