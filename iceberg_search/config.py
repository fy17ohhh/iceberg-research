from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv


load_dotenv()


def model_id_from_env(default: str = "deepseek-v4-flash") -> str:
    return (
        os.getenv("LLM_MODEL_ID")
        or os.getenv("MODEL_ID")
        or os.getenv("model_id")
        or default
    )


@dataclass
class LLMConfig:
    model: str = model_id_from_env()
    sonar_model: str = os.getenv("SONAR_MODEL_ID", "")
    temperature: float = 0.0
    diver_temperature: float = 0.6
    synthesizer_temperature: float = 0.3
    timeout: int = 120


@dataclass
class ContextConfig:
    max_tokens: int = 30000
    reserve_ratio: float = 0.15


@dataclass
class SonarConfig:
    batch_size: int = int(os.getenv("SONAR_BATCH_SIZE", "2"))
    max_attempts: int = int(os.getenv("SONAR_MAX_ATTEMPTS", "3"))


@dataclass
class Config:
    config_dir: str = "configs"
    data_dir: str = "data"
    max_rounds: int = 3
    max_steps: int = 3
    llm: LLMConfig = field(default_factory=LLMConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    sonar: SonarConfig = field(default_factory=SonarConfig)
