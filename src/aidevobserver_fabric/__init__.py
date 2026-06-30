"""AIDevObserver capability fabric."""

from .models import CandidateBundle, PrimitiveRecord, ServiceRecord
from .openwebui import OpenWebUIConfig
from .primitive_factory import PrimitiveGenome
from .social_ingest import RapidApiProviderSpec, SocialSource
from .source_surfaces import SourceSurface

__all__ = [
    "CandidateBundle",
    "OpenWebUIConfig",
    "PrimitiveRecord",
    "PrimitiveGenome",
    "RapidApiProviderSpec",
    "ServiceRecord",
    "SocialSource",
    "SourceSurface",
]
