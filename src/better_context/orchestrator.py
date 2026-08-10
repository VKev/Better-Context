"""Orchestrator module for better-context.

This is the main entry point that wires together all the analysis and generation
modules into a coherent pipeline. It provides both high-level APIs for the CLI
and lower-level control for programmatic usage.

Pipeline Flow:
1. Scan: Walk repository → FileInventory
2. Parse: Extract chunks/imports/exports from each file → ParseResult
3. Resolve: Resolve imports to file paths → ResolutionResult
4. Graph: Build dependency graph → DependencyGraph
5. Analyze: Calculate centrality, detect cycles, build layers
6. Manifest: Assemble all data into a Manifest
7. Generate: Create AGENTS.md files from manifest
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Dict, List, Optional, Any

from .config import Config, load_config
from .scanner import walk_repository, FileInventory, FileInfo
from .languages import detect_language, SUPPORTED_LANGUAGES
from .chunker import parse_file as chunk_parse_file
from .resolution import RawImport, resolve_all_imports, ResolutionResult
from .graph import build_dependency_graph, DependencyGraph, get_graph_stats, detect_cycles, build_topological_layers
from .centrality import calculate_pagerank, get_top_files, find_cycles as centrality_find_cycles
from .manifest import (
    Manifest, ManifestMeta, FileEntry, ChunkEntry, ImportEntry, ExportEntry,
    GraphData, ParseError, create_manifest_meta, save_manifest, load_manifest,
    MANIFEST_VERSION,
)
from .agents_map import generate_agents_map, load_summaries
from .staleness import save_staleness_info
from .architecture import analyze_architecture
from .coupling import calculate_coupling_metrics
from .roslyn import RoslynUnavailableError, analyze_csharp_project, discover_project_references
from .unity_intelligence import (
    classify_ownership,
    collect_project_facts,
    is_unity_project,
)
from .unity_runtime import UnityRuntimeAnalysis, analyze_unity_runtime


def _merge_edge_details(details: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one deterministic evidence record per graph edge."""
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    confidence_rank = {"exact": 4, "structured": 3, "resolved": 2, "partial": 1}

    def evidence_items(detail: dict[str, Any]) -> list[Any]:
        raw = detail.get("evidence", [])
        if isinstance(raw, list):
            return list(raw)
        return [raw] if raw else []

    for detail in details:
        source = str(detail.get("source", ""))
        target = str(detail.get("target", ""))
        if not source or not target or target.endswith(".meta"):
            continue
        key = (source, target)
        if key not in merged:
            normalized = {
                **detail,
                "source": source,
                "target": target,
                "kinds": sorted(set(detail.get("kinds", []))),
                "symbols": sorted(set(detail.get("symbols", []))),
                "lines": sorted(set(detail.get("lines", []))),
            }
            if detail.get("evidence"):
                normalized["evidence"] = evidence_items(detail)
            merged[key] = normalized
            continue

        current = merged[key]
        current["kinds"] = sorted(
            set(current.get("kinds", [])) | set(detail.get("kinds", []))
        )
        current["symbols"] = sorted(
            set(current.get("symbols", [])) | set(detail.get("symbols", []))
        )
        current["lines"] = sorted(
            set(current.get("lines", [])) | set(detail.get("lines", []))
        )
        current_confidence = str(current.get("confidence", "partial"))
        new_confidence = str(detail.get("confidence", "partial"))
        if confidence_rank.get(new_confidence, 0) > confidence_rank.get(current_confidence, 0):
            current["confidence"] = new_confidence

        engines = {
            str(engine)
            for engine in [
                current.get("engine"),
                detail.get("engine"),
                *current.get("engines", []),
                *detail.get("engines", []),
            ]
            if engine
        }
        if len(engines) > 1:
            current["engine"] = "mixed"
            current["engines"] = sorted(engines - {"mixed"})

        incoming_evidence = evidence_items(detail)
        if incoming_evidence:
            evidence = current.setdefault("evidence", [])
            for item in incoming_evidence:
                if item not in evidence:
                    evidence.append(item)

    return [merged[key] for key in sorted(merged)]


@dataclass
class AnalysisResult:
    """Complete analysis result from the pipeline."""
    
    inventory: FileInventory
    parsed_files: Dict[str, Any]  # path -> ParseResult
    resolution: ResolutionResult
    graph: DependencyGraph
    centrality: Dict[str, float]
    cycles: List[List[str]]
    layers: List[List[str]]
    manifest: Manifest
    timing: Dict[str, float] = field(default_factory=dict)
    
    @property
    def file_count(self) -> int:
        return len(self.inventory.files)
    
    @property
    def has_cycles(self) -> bool:
        return len(self.cycles) > 0


@dataclass 
class OrchestrationResult:
    """Result of a complete orchestration run (analyze + generate)."""
    
    analysis: AnalysisResult
    # generation: GeneratorResult
    generation: Any = None # Typed as Any to avoid import error if GeneratorResult is gone
    total_time_ms: int = 0


ProgressCallback = Callable[[str, int, int], None]


class Orchestrator:
    """Main orchestrator for the better-context pipeline.
    
    Usage:
        orchestrator = Orchestrator(Path("./my-project"))
        result = orchestrator.run()
        # result.analysis contains parsed data
        # result.generation contains generated file paths
    """
    
    def __init__(
        self,
        root: Path,
        config: Optional[Config] = None,
        config_path: Optional[Path] = None,
    ):
        """Initialize the orchestrator.
        
        Args:
            root: Project root directory
            config: Optional pre-loaded config
            config_path: Optional path to config file
        """
        self.root = root.resolve()
        self.config = config or load_config(self.root, config_path)
        self._progress_callback: Optional[ProgressCallback] = None
        self._edge_details: List[Dict[str, Any]] = []
        self._csharp_calls: List[Dict[str, Any]] = []
        self._unity_runtime: Optional[UnityRuntimeAnalysis] = None
        self._analysis_engine = "language-adapters"
    
    def set_progress_callback(self, callback: ProgressCallback) -> None:
        """Set a callback for progress updates.
        
        Args:
            callback: Function(phase: str, current: int, total: int)
        """
        self._progress_callback = callback
    
    def _report_progress(self, phase: str, current: int, total: int) -> None:
        """Report progress if callback is set."""
        if self._progress_callback:
            self._progress_callback(phase, current, total)
    
    def run(
        self,
        generate: bool = True,
        max_depth: int = -1,
        output_root: Optional[Path] = None,
    ) -> OrchestrationResult:
        """Run the complete pipeline: analyze and optionally generate.
        
        Args:
            generate: Whether to generate AGENTS.md files
            max_depth: Maximum depth for AGENTS.md generation (-1 = unlimited)
            output_root: Where to write AGENTS.md files (default: project root)
        
        Returns:
            OrchestrationResult with analysis and generation data
        """
        start_time = time.time()
        
        # Step 1: Analyze
        analysis = self.analyze()
        
        # Step 2: Generate (if requested)
        generation = None
        if generate and self.config.generate_agents_md:
            generation = self.generate(
                analysis.manifest,
                analysis.graph,
                max_depth=max_depth,
                output_root=output_root,
            )

            file_hashes = {
                f.path: f.content_hash
                for f in analysis.inventory.files
                if not f.path.endswith("AGENTS.md")
            }
            save_staleness_info(
                self.root,
                file_hashes,
                analysis.manifest.meta.generated_at,
                self.config.output_dir,
            )
        
        total_time_ms = int((time.time() - start_time) * 1000)
        
        return OrchestrationResult(
            analysis=analysis,
            generation=generation,
            total_time_ms=total_time_ms,
        )
    
    def analyze(self) -> AnalysisResult:
        """Run analysis pipeline without generating AGENTS.md.
        
        Returns:
            AnalysisResult with all parsed data
        """
        timing: Dict[str, float] = {}
        
        # Phase 1: Scan repository
        t0 = time.time()
        inventory = self._scan_repository()
        timing['scan'] = time.time() - t0
        
        # Phase 2: Parse files
        t0 = time.time()
        parsed_files, parse_errors = self._parse_files(inventory)
        timing['parse'] = time.time() - t0
        
        # Phase 3: Resolve imports and build graph
        t0 = time.time()
        resolution, graph = self._build_graph(parsed_files, inventory)
        timing['graph'] = time.time() - t0
        
        # Phase 4: Analyze graph (centrality, cycles, layers)
        t0 = time.time()
        centrality = calculate_pagerank(graph, damping=self.config.pagerank_damping)
        cycles = detect_cycles(graph)
        layers = build_topological_layers(graph)
        timing['analysis'] = time.time() - t0
        
        # Phase 5: Build manifest
        t0 = time.time()
        manifest = self._build_manifest(
            inventory, parsed_files, parse_errors,
            graph, centrality, cycles, layers
        )
        timing['manifest'] = time.time() - t0
        
        return AnalysisResult(
            inventory=inventory,
            parsed_files=parsed_files,
            resolution=resolution,
            graph=graph,
            centrality=centrality,
            cycles=cycles,
            layers=layers,
            manifest=manifest,
            timing=timing,
        )
    
    def generate(
        self,
        manifest: Manifest,
        graph: DependencyGraph,
        max_depth: int = -1,
        output_root: Optional[Path] = None,
    ) -> Any:
        """Generate safe, marker-managed AGENTS.md maps from a manifest.
        
        Args:
            manifest: Analysis manifest
            graph: Dependency graph
            max_depth: Maximum depth for generation (-1 = unlimited)
            output_root: Where to write files (default: project root)
        
        Returns:
            GeneratorResult with list of generated files
        """
        return generate_agents_map(
            manifest,
            graph,
            output_root or self.root,
            max_depth=max_depth,
            summaries=load_summaries(self.root),
        )
    
    def save_manifest(self, manifest: Manifest, path: Optional[Path] = None) -> Path:
        """Save manifest to JSON file.
        
        Args:
            manifest: Manifest to save
            path: Output path (default: .better-context/manifest.json)
        
        Returns:
            Path to saved manifest
        """
        if path is None:
            output_dir = self.root / self.config.output_dir
            output_dir.mkdir(parents=True, exist_ok=True)
            path = output_dir / self.config.manifest_file
        
        save_manifest(manifest, path)
        return path
    
    def load_manifest(self, path: Optional[Path] = None) -> Manifest:
        """Load manifest from JSON file.
        
        Args:
            path: Input path (default: .better-context/manifest.json)
        
        Returns:
            Loaded manifest
        """
        if path is None:
            path = self.root / self.config.output_dir / self.config.manifest_file
        
        return load_manifest(path)
    
    def _scan_repository(self) -> FileInventory:
        """Scan repository and build file inventory."""
        def language_detector(path: Path) -> Optional[str]:
            return detect_language(path, self.config)
        
        inventory = walk_repository(
            self.root,
            max_file_size_kb=self.config.max_file_size_kb,
            language_detector=language_detector,
        )
        
        self._report_progress('scan', len(inventory.files), len(inventory.files))
        return inventory
    
    def _parse_files(
        self,
        inventory: FileInventory,
    ) -> tuple[Dict[str, Any], List[ParseError]]:
        """Parse all files and extract chunks/imports/exports."""
        self._edge_details = []
        self._csharp_calls = []
        self._unity_runtime = None
        self._analysis_engine = "language-adapters"
        parsed: Dict[str, Any] = {}
        errors: List[ParseError] = []
        total = len(inventory.files)

        csharp_files = [
            entry for entry in inventory.files if entry.language == "csharp"
        ]
        if csharp_files:
            try:
                analysis = analyze_csharp_project(
                    self.root,
                    [entry.path for entry in csharp_files],
                    discover_project_references(self.root),
                )
                parsed.update(analysis.parsed_files)
                self._edge_details = [
                    {
                        **detail,
                        "confidence": "exact",
                        "engine": "roslyn",
                    }
                    for detail in analysis.dependencies
                ]
                self._csharp_calls = analysis.calls
                self._analysis_engine = analysis.engine
                for diagnostic in analysis.diagnostics[:100]:
                    errors.append(ParseError(
                        path=diagnostic.split(":", 1)[0],
                        error_type="parse",
                        message=diagnostic,
                    ))
            except RoslynUnavailableError as error:
                self._analysis_engine = "regex-symbols-only"
                errors.append(ParseError(
                    path="<csharp-project>",
                    error_type="analysis",
                    message=(
                        f"{error} C# dependency and call edges were omitted to avoid "
                        "name-based false positives."
                    ),
                ))
        
        for i, file_info in enumerate(inventory.files):
            self._report_progress('parse', i + 1, total)
            
            # Skip files without language detection
            if not file_info.language:
                continue
            
            # Skip unsupported languages
            if file_info.language not in SUPPORTED_LANGUAGES:
                continue

            # Roslyn parsed C# as one compilation. Missing files fall through to
            # the regex adapter for symbol inventory only.
            if file_info.path in parsed:
                continue
            
            try:
                source = file_info.absolute_path.read_text(encoding='utf-8')
                result = chunk_parse_file(
                    file_info.path,
                    source,
                    file_info.language,
                )
                parsed[file_info.path] = result
                
                if result.errors:
                    for err in result.errors:
                        errors.append(ParseError(
                            path=file_info.path,
                            error_type='parse',
                            message=err,
                        ))
                        
            except UnicodeDecodeError as e:
                errors.append(ParseError(
                    path=file_info.path,
                    error_type='encoding',
                    message=str(e),
                ))
            except Exception as e:
                errors.append(ParseError(
                    path=file_info.path,
                    error_type='parse',
                    message=str(e),
                ))
        
        return parsed, errors
    
    def _build_graph(
        self,
        parsed_files: Dict[str, Any],
        inventory: FileInventory,
    ) -> tuple[ResolutionResult, DependencyGraph]:
        """Build dependency graph from parsed imports."""
        # Convert ParseResult imports to RawImport for resolution
        files_imports: Dict[str, List[RawImport]] = {}
        
        for path, parse_result in parsed_files.items():
            raw_imports = []
            # A C# using directive names a namespace, not a file. Resolving it
            # through the generic path resolver caused System -> System.meta.
            source_imports = [] if path.endswith(".cs") else parse_result.imports
            for imp in source_imports:
                raw_imports.append(RawImport(
                    specifier=imp.module,
                    symbols=imp.symbols,
                    alias=imp.alias,
                    line=imp.line,
                    is_relative=imp.is_relative,
                    is_type_only=getattr(imp, 'is_type_only', False),
                ))
            files_imports[path] = raw_imports
        
        # Get all file paths
        all_paths = [f.path for f in inventory.files if not f.path.endswith("AGENTS.md")]
        
        # Build graph
        graph, resolution = build_dependency_graph(
            files_imports,
            all_paths,
            self.root,
        )

        self._add_verified_edges(graph, inventory, parsed_files)
        
        return resolution, graph

    def _add_verified_edges(
        self,
        graph: DependencyGraph,
        inventory: FileInventory,
        parsed_files: Dict[str, Any],
    ) -> None:
        """Add semantic C# and structured Unity runtime edges to the shared graph."""
        for detail in self._edge_details:
            graph.add_edge(detail["source"], detail["target"])

        if is_unity_project(self.root):
            runtime_files = [
                SimpleNamespace(
                    path=entry.path,
                    chunks=list(getattr(parsed_files.get(entry.path), "chunks", [])),
                    metadata={"ownership": classify_ownership(entry.path)},
                )
                for entry in inventory.files
            ]
            self._unity_runtime = analyze_unity_runtime(
                self.root,
                inventory,
                runtime_files,
                scope=self.config.unity_asset_scope,
            )
            self._unity_runtime.summary.setdefault("scope", self.config.unity_asset_scope)
            self._unity_runtime.summary["agents_limits"] = {
                "assets": self.config.unity_agents_asset_limit,
                "objects": self.config.unity_agents_object_limit,
            }
            for asset_path, asset in self._unity_runtime.assets.items():
                if asset.get("status") == "parsed":
                    graph.add_node(asset_path)
            valid_nodes = set(graph.nodes)
            for detail in self._unity_runtime.edge_details:
                source = detail.get("source", "")
                target = detail.get("target", "")
                if (
                    source not in valid_nodes
                    or target not in valid_nodes
                    or target.endswith(".meta")
                ):
                    continue
                normalized = {
                    **detail,
                    "confidence": detail.get("confidence", "structured"),
                    "engine": detail.get("engine", "unity-yaml"),
                }
                self._edge_details.append(normalized)
                graph.add_edge(source, target)
            self._csharp_calls.extend(self._unity_runtime.call_graph)

        self._edge_details = _merge_edge_details(self._edge_details)

        detailed_pairs = {
            (detail["source"], detail["target"])
            for detail in self._edge_details
        }
        for source, target in graph.get_all_edges():
            if (source, target) not in detailed_pairs:
                self._edge_details.append({
                    "source": source,
                    "target": target,
                    "kinds": ["import"],
                    "symbols": [],
                    "lines": [],
                    "confidence": "resolved",
                    "engine": "language-adapter",
                })

        self._edge_details = _merge_edge_details(self._edge_details)
    
    def _build_manifest(
        self,
        inventory: FileInventory,
        parsed_files: Dict[str, Any],
        parse_errors: List[ParseError],
        graph: DependencyGraph,
        centrality: Dict[str, float],
        cycles: List[List[str]],
        layers: List[List[str]],
    ) -> Manifest:
        """Assemble all data into a Manifest."""
        # Compute config hash for cache invalidation
        config_hash = hashlib.sha256(
            str(vars(self.config)).encode()
        ).hexdigest()[:16]
        
        meta = create_manifest_meta(self.root, config_hash)
        
        # Build file entries
        files: List[FileEntry] = []
        for file_info in inventory.files:
            parse_result = parsed_files.get(file_info.path)
            
            chunks = []
            imports = []
            exports = []
            
            if parse_result:
                for chunk in parse_result.chunks:
                    chunks.append(ChunkEntry(
                        id=chunk.id,
                        type=chunk.type,
                        name=chunk.name,
                        signature=chunk.signature,
                        start_line=chunk.start_line,
                        end_line=chunk.end_line,
                        parent=chunk.parent,
                        exported=chunk.exported,
                        docstring=chunk.docstring,
                        metadata=chunk.metadata,
                        semantic_anchor=chunk.semantic_anchor,
                    ))
                
                for imp in parse_result.imports:
                    imports.append(ImportEntry(
                        module=imp.module,
                        symbols=imp.symbols,
                        alias=imp.alias,
                        is_relative=imp.is_relative,
                        line=imp.line,
                    ))
                
                for exp in parse_result.exports:
                    exports.append(ExportEntry(
                        name=exp.name,
                        type=exp.type,
                        line=exp.line,
                        is_default=exp.is_default,
                    ))
            
            files.append(FileEntry(
                path=file_info.path,
                language=file_info.language or '',
                size_bytes=file_info.size_bytes,
                hash=file_info.content_hash,
                chunks=chunks,
                imports=imports,
                exports=exports,
                metadata={"ownership": classify_ownership(file_info.path)},
            ))

        if self._unity_runtime is not None:
            for entry in files:
                runtime_metadata = self._unity_runtime.assets.get(entry.path)
                if runtime_metadata is not None:
                    entry.metadata["unity_runtime"] = runtime_metadata

        source_files = [
            entry for entry in files
            if entry.language and not entry.path.endswith("AGENTS.md")
        ]
        coupling = {
            entry.path: asdict(calculate_coupling_metrics(entry.path, graph, files))
            for entry in source_files
        }
        architecture_files = [
            entry for entry in source_files
            if entry.metadata.get("ownership") in {"project-owned", "repository"}
        ]
        architecture_report = analyze_architecture(architecture_files, graph)
        architecture = {
            "layers": architecture_report.layers,
            "violations": [asdict(item) for item in architecture_report.violations],
            "classifications": {
                path: asdict(item)
                for path, item in architecture_report.classifications.items()
            },
            "stats": architecture_report.stats,
        }
        for entry in files:
            if entry.path in coupling:
                entry.metadata["coupling"] = coupling[entry.path]
            classification = architecture_report.classifications.get(entry.path)
            if classification:
                entry.metadata["architecture"] = asdict(classification)

        analyzed_files = [entry for entry in files if not entry.path.endswith("AGENTS.md")]
        analyzed_source_files = [entry for entry in analyzed_files if entry.language]
        project = collect_project_facts(self.root, [entry.path for entry in analyzed_files])
        project["analysis_engine"] = self._analysis_engine
        if self._unity_runtime is not None:
            project["unity_runtime"] = self._unity_runtime.summary
            project["unity_analysis_engine"] = "unity-yaml-structured-v1"
        ownership_by_path = {
            entry.path: entry.metadata.get("ownership", "repository") for entry in analyzed_files
        }
        project_edges = [
            (source, target)
            for source, target in graph.get_all_edges()
            if ownership_by_path.get(source) in {"project-owned", "repository"}
            and ownership_by_path.get(target) in {"project-owned", "repository"}
        ]
        project_cycles = [
            cycle for cycle in cycles
            if all(
                ownership_by_path.get(path) in {"project-owned", "repository"}
                for path in cycle
            )
        ]
        project["project_cycles"] = project_cycles
        serialized_kinds = {
            "serialized_guid",
            "unity_component",
            "scriptable_object_type",
            "prefab_instance",
            "animator_motion",
            "unity_event",
        }
        project["metrics"] = {
            "files": len(analyzed_files),
            "source_files": len(analyzed_source_files),
            "symbols": sum(len(entry.chunks) for entry in analyzed_files),
            "public_symbols": sum(
                sum(1 for chunk in entry.chunks if chunk.exported) for entry in analyzed_files
            ),
            "dependencies": len(graph.get_all_edges()),
            "project_owned_dependencies": len(project_edges),
            "semantic_csharp_dependencies": sum(
                1
                for item in self._edge_details
                if item.get("engine") == "roslyn" or "roslyn" in item.get("engines", [])
            ),
            "serialized_dependencies": sum(
                1
                for item in self._edge_details
                if serialized_kinds.intersection(item.get("kinds", []))
            ),
            "roslyn_call_sites": sum(
                1 for item in self._csharp_calls if item.get("kind") != "unity_event"
            ),
            "unity_event_calls": sum(
                1 for item in self._csharp_calls if item.get("kind") == "unity_event"
            ),
            "call_sites": len(self._csharp_calls),
            "cycles": len(cycles),
            "project_owned_cycles": len(project_cycles),
        }
        
        # Build graph data
        graph_data = GraphData(
            nodes=list(graph.nodes),
            edges=graph.get_all_edges(),
            centrality=centrality,
            layers=layers,
            cycles=cycles,
            edge_details=self._edge_details,
            call_graph=self._csharp_calls,
            coupling=coupling,
            architecture=architecture,
        )
        
        all_errors = list(parse_errors)
        if self._unity_runtime is not None:
            for error in self._unity_runtime.errors[:100]:
                all_errors.append(ParseError(
                    path=str(error.get("path", "<unity-asset>")),
                    error_type=str(error.get("error_type", "unity-runtime")),
                    message=str(error.get("message", "Unity runtime analysis failed")),
                    line=error.get("line"),
                ))

        return Manifest(
            meta=meta,
            files=files,
            graph=graph_data,
            errors=all_errors,
            project=project,
        )


def analyze_codebase(
    root: Path,
    config: Optional[Config] = None,
    progress_callback: Optional[ProgressCallback] = None,
) -> AnalysisResult:
    """Convenience function to analyze a codebase.
    
    Args:
        root: Project root directory
        config: Optional configuration
        progress_callback: Optional progress callback
    
    Returns:
        AnalysisResult with all analysis data
    """
    orchestrator = Orchestrator(root, config)
    if progress_callback:
        orchestrator.set_progress_callback(progress_callback)
    return orchestrator.analyze()


def generate_context(
    root: Path,
    max_depth: int = -1,
    config: Optional[Config] = None,
    progress_callback: Optional[ProgressCallback] = None,
) -> OrchestrationResult:
    """Convenience function to analyze and generate AGENTS.md.
    
    Args:
        root: Project root directory
        max_depth: Maximum depth for AGENTS.md generation
        config: Optional configuration
        progress_callback: Optional progress callback
    
    Returns:
        OrchestrationResult with analysis and generation data
    """
    orchestrator = Orchestrator(root, config)
    if progress_callback:
        orchestrator.set_progress_callback(progress_callback)
    return orchestrator.run(generate=True, max_depth=max_depth)


__all__ = [
    'Orchestrator',
    'AnalysisResult',
    'OrchestrationResult',
    'ProgressCallback',
    'analyze_codebase',
    'generate_context',
]
