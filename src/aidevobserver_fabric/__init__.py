"""AIDevObserver capability fabric."""

from .models import CandidateBundle, PrimitiveRecord, ServiceRecord
from .edge_catalog import CatalogLocation
from .ollama import OllamaConfig
from .openwebui import OpenWebUIConfig
from .primitive_factory import PrimitiveGenome
from .social_ingest import RapidApiProviderSpec, SocialSource
from .source_surfaces import SourceSurface

__all__ = [
    "CandidateBundle",
    "CatalogLocation",
    "OllamaConfig",
    "OpenWebUIConfig",
    "PrimitiveRecord",
    "PrimitiveGenome",
    "RapidApiProviderSpec",
    "ServiceRecord",
    "SocialSource",
    "SourceSurface",
]
