"""AIDevObserver capability fabric."""

from .models import CandidateBundle, PrimitiveRecord, ServiceRecord
from .ollama import OllamaConfig
from .openwebui import OpenWebUIConfig
from .primitive_factory import PrimitiveGenome
from .social_ingest import RapidApiProviderSpec, SocialSource
from .source_surfaces import SourceSurface

__all__ = [
    "CandidateBundle",
    "OllamaConfig",
    "OpenWebUIConfig",
    "PrimitiveRecord",
    "PrimitiveGenome",
    "RapidApiProviderSpec",
    "ServiceRecord",
    "SocialSource",
    "SourceSurface",
]
