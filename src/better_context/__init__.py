"""Better Context: AI Agent Codebase Intelligence CLI.

A CLI tool that programmatically processes codebases, breaking them into
mathematically structured, semantically meaningful pieces that AI agents
can progressively consume.
"""

__version__ = "1.6.0"

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
# Post-MVP: Token Budget Optimizer
from better_context.optimizer import (
    ScoredChunk,
    OptimizationResult,
    optimize_context,
    optimize_context_greedy,
    optimize_context_knapsack,
    estimate_tokens,
    estimate_chunk_tokens,
    calculate_relevance,
    calculate_diversity_penalty,
    prepare_chunks,
    format_optimization_result,
)
# Post-MVP: Focus Mode (Ego-Centric Context)
from better_context.focus import (
    FocusedFile,
    FocusedContext,
    FocusConfig,
    compute_focus_context,
    generate_focus_markdown,
    select_within_budget,
)
# Post-MVP: Semantic Anchors (Content-Addressable Chunks)
from better_context.semantic_anchor import (
    SemanticAnchor,
    AnchorMapping,
    compute_semantic_anchor,
    compute_signature_anchor,
    normalize_code,
    resolve_anchor,
    update_anchor_mapping,
    anchor_mapping_to_dict,
    dict_to_anchor_mapping,
)
from better_context.unity_runtime import UnityRuntimeAnalysis, analyze_unity_runtime
from better_context.primitives import (
    DepsResult,
    EntriesResult,
    FileInfoResult,
    OverviewResult,
    ProjectDetection,
    ProjectTooling,
    ScriptsResult,
    TreeResult,
    detect_project_tooling,
    detect_tooling,
    get_deps,
    get_entries,
    get_file_info,
    get_overview,
    get_scripts,
    get_tree,
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
    # Post-MVP: Token Budget Optimizer
    "ScoredChunk",
    "OptimizationResult",
    "optimize_context",
    "optimize_context_greedy",
    "optimize_context_knapsack",
    "estimate_tokens",
    "estimate_chunk_tokens",
    "calculate_relevance",
    "calculate_diversity_penalty",
    "prepare_chunks",
    "format_optimization_result",
    # Post-MVP: Focus Mode (Ego-Centric Context)
    "FocusedFile",
    "FocusedContext",
    "FocusConfig",
    "compute_focus_context",
    "generate_focus_markdown",
    "select_within_budget",
    # Post-MVP: Semantic Anchors (Content-Addressable Chunks)
    "SemanticAnchor",
    "AnchorMapping",
    "compute_semantic_anchor",
    "compute_signature_anchor",
    "normalize_code",
    "resolve_anchor",
    "update_anchor_mapping",
    "anchor_mapping_to_dict",
    "dict_to_anchor_mapping",
    # Unity runtime intelligence
    "UnityRuntimeAnalysis",
    "analyze_unity_runtime",
    # Primitives
    "DepsResult",
    "EntriesResult",
    "FileInfoResult",
    "OverviewResult",
    "ProjectDetection",
    "ProjectTooling",
    "ScriptsResult",
    "TreeResult",
    "detect_project_tooling",
    "detect_tooling",
    "get_deps",
    "get_entries",
    "get_file_info",
    "get_overview",
    "get_scripts",
    "get_tree",
]
