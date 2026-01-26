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
from dataclasses import dataclass, field
from pathlib import Path
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
# from .generator import generate_agents_md, GeneratorConfig, GeneratorResult
from .staleness import save_staleness_info


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
        generation = None # GeneratorResult()
        # if generate:
        #     generation = self.generate(
        #         analysis.manifest,
        #         analysis.graph,
        #         max_depth=max_depth,
        #         output_root=output_root,
        #     )
        #     
        #     # Step 3: Save staleness info for verification
        #     # Exclude AGENTS.md files since they are our output, not input
        #     file_hashes = {
        #         f.path: f.content_hash
        #         for f in analysis.inventory.files
        #         if not f.path.endswith("AGENTS.md")
        #     }
        #     save_staleness_info(
        #         self.root,
        #         file_hashes,
        #         analysis.manifest.meta.generated_at,
        #         self.config.output_dir,
        #     )
        
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
        """Generate AGENTS.md files from manifest.
        
        DEPRECATED: This method relies on deprecated generator.py logic.
        Future versions will remove this as agents should generate their own context.
        
        Args:
            manifest: Analysis manifest
            graph: Dependency graph
            max_depth: Maximum depth for generation (-1 = unlimited)
            output_root: Where to write files (default: project root)
        
        Returns:
            GeneratorResult with list of generated files
        """
        # output_root = output_root or self.root
        
        # try:
        #     from .generator import generate_agents_md, GeneratorConfig, GeneratorResult
        #     
        #     gen_config = GeneratorConfig(
        #         max_depth=max_depth,
        #         max_key_files=10,
        #         include_metrics=True,
        #         include_diagrams=True,
        #     )
        #     
        #     return generate_agents_md(manifest, graph, output_root, gen_config)
        # except ImportError:
        #     # Handle case where generator is already removed
        #     print("Warning: Generator module not found. AGENTS.md generation skipped.", file=sys.stderr)
        #     return GeneratorResult()
        return None
    
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
        parsed: Dict[str, Any] = {}
        errors: List[ParseError] = []
        total = len(inventory.files)
        
        for i, file_info in enumerate(inventory.files):
            self._report_progress('parse', i + 1, total)
            
            # Skip files without language detection
            if not file_info.language:
                continue
            
            # Skip unsupported languages
            if file_info.language not in SUPPORTED_LANGUAGES:
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
            for imp in parse_result.imports:
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
        all_paths = [f.path for f in inventory.files]
        
        # Build graph
        graph, resolution = build_dependency_graph(
            files_imports,
            all_paths,
            self.root,
        )
        
        return resolution, graph
    
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
            ))
        
        # Build graph data
        graph_data = GraphData(
            nodes=list(graph.nodes),
            edges=graph.get_all_edges(),
            centrality=centrality,
            layers=layers,
            cycles=cycles,
        )
        
        return Manifest(
            meta=meta,
            files=files,
            graph=graph_data,
            errors=parse_errors,
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
