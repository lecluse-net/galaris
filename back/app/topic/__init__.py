"""Global thematic dossiers, classified by Dream before memory projection."""

from .models import Topic
from .privileges import TOPIC_ACCESS, TOPIC_EDIT
from .schemas import (
    TopicCandidate,
    TopicClassification,
    TopicCreate,
    TopicItemKind,
    TopicItemMutationResult,
    TopicItemPage,
    TopicItemRead,
    TopicItemSelector,
    TopicLinkedMemoryRead,
    TopicMergeRequest,
    TopicMutationResult,
    TopicMonthlyUsage,
    TopicPage,
    TopicRead,
    TopicSplitRequest,
    TopicSelectionSplitRequest,
    TopicUpdate,
)
from .sequential_detection import (
    PromptedTopicDetectionModel,
    TopicDetectionCatalog,
    TopicDetectionConfigurationError,
    TopicDetectionDependencies,
    TopicDetectionModel,
    detect_topic,
    use_topic_detection_dependencies,
)
from .runtime_detection import runtime_topic_detection_dependencies
from .qualification import (
    TopicContinuityObservation,
    TopicContinuityQualification,
    qualify_topic_continuity,
)
from .evaluation import TopicDetectionLabInput
from . import service

__all__ = [
    "TOPIC_ACCESS",
    "TOPIC_EDIT",
    "Topic",
    "TopicDetectionLabInput",
    "TopicCandidate",
    "TopicClassification",
    "TopicCreate",
    "TopicItemKind",
    "TopicItemMutationResult",
    "TopicItemPage",
    "TopicItemRead",
    "TopicItemSelector",
    "TopicLinkedMemoryRead",
    "TopicMergeRequest",
    "TopicMutationResult",
    "TopicMonthlyUsage",
    "TopicPage",
    "TopicRead",
    "TopicSplitRequest",
    "TopicSelectionSplitRequest",
    "TopicUpdate",
    "PromptedTopicDetectionModel",
    "TopicDetectionCatalog",
    "TopicDetectionConfigurationError",
    "TopicDetectionDependencies",
    "TopicDetectionModel",
    "detect_topic",
    "runtime_topic_detection_dependencies",
    "TopicContinuityObservation",
    "TopicContinuityQualification",
    "qualify_topic_continuity",
    "service",
    "use_topic_detection_dependencies",
]
