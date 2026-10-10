"""Shared contracts for RepoLens.

Every other package (`parser`, `analyzer`, `graph`) and the API
layer speak these types, so a change here is a change to the platform contract.
"""

from .constants import (
    ANALYSIS_STAGES,
    BINARY_EXTENSIONS,
    DEFAULT_IGNORED_DIRS,
    DOC_LANGUAGES,
    EXAMPLE_PATH_PATTERNS,
    FRAMEWORK_MARKERS,
    GRAPH_LANGUAGES,
    LANGUAGE_BY_EXTENSION,
    LANGUAGE_BY_NAME,
    LANGUAGE_LABELS,
    MANIFEST_FILES,
    TEST_PATH_PATTERNS,
    Language,
    Stage,
)
from .errors import (
    AnalysisCancelledError,
    AnalysisNotReadyError,
    DatabaseError,
    EmptyRepositoryError,
    GitHostError,
    GitHubAuthError,
    GitHubRateLimitError,
    InvalidRepoUrlError,
    ParseError,
    RepoNotFoundError,
    RepoLensError,
    RepoTooLargeError,
    UnsupportedLanguageError,
)
from .schemas import (
    AnalysisOverview,
    AnalysisRun,
    AnalysisStatus,
    ApiEndpoint,
    ArchitectureGraph,
    Branch,
    CodeChunk,
    DependencyEdge,
    DependencyGraph,
    ImpactReport,
    QualityIssue,
    RepoMetadata,
    RepoRef,
    RepoSummary,
    SearchHit,
    SourceFile,
    SymbolInfo,
    Workflow,
    WorkflowStep,
)
from .utils import (
    is_doc_path,
    is_example_path,
    is_probably_binary,
    language_for_path,
    normalize_repo_url,
    relative_time,
    sha1,
    shingle_hash,
    stable_id,
    truncate,
)

__all__ = [name for name in dir() if not name.startswith("_")]
__version__ = "0.1.0"
