"""
name: llm_factory
description: Factory returning LangChain BaseChatModel instances across Gemini, Ollama, and Hugging Face stages.
"""

from typing import Tuple

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from src.core.config import AIBackend, Settings, get_settings


class LLMFactory:
    """Creates unified LangChain chat model instances based on the selected AI backend stage."""

    @staticmethod
    def get_chat_model(
        backend: AIBackend | None = None,
        temperature: float = 0.7,
        settings: Settings | None = None,
    ) -> Tuple[BaseChatModel, str]:
        """
        Instantiate a LangChain BaseChatModel and return it with its model identifier.

        Parameters:
            backend (AIBackend | None): Target AI stage ('gemini', 'ollama', 'huggingface'); defaults to settings.
            temperature (float): Sampling temperature for generation.
            settings (Settings | None): Optional settings override for testing.
        Returns:
            Tuple[BaseChatModel, str]: Configured LangChain chat model and model name string.
        Raises:
            ValueError: If an unsupported backend is requested or required credentials are missing.
        """
        cfg = settings or get_settings()
        target = backend or cfg.ai_backend

        if target == AIBackend.GEMINI:
            if not cfg.gemini_api_key:
                raise ValueError("GEMINI_API_KEY must be configured when using the Gemini backend.")
            model = ChatGoogleGenerativeAI(
                model=cfg.gemini_model,
                google_api_key=cfg.gemini_api_key,
                temperature=temperature,
                timeout=30.0,
                max_retries=3,
            )
            return model, cfg.gemini_model

        if target == AIBackend.OLLAMA:
            model = ChatOllama(
                model=cfg.ollama_model,
                base_url=cfg.resolved_ollama_base_url,
                temperature=temperature,
            )
            return model, cfg.ollama_model

        if target == AIBackend.HUGGINGFACE:
            model = ChatOpenAI(
                model=cfg.hf_model_id,
                base_url=cfg.hf_serving_url,
                api_key=cfg.hf_api_key,
                temperature=temperature,
            )
            return model, cfg.hf_model_id

        raise ValueError(f"Unsupported AI backend: {target}")

    @staticmethod
    def get_gemini_fallback_model(
        temperature: float = 0.7,
        settings: Settings | None = None,
    ) -> Tuple[BaseChatModel, str]:
        """
        Instantiate the configured fallback Gemini chat model for handling high demand (503).

        Parameters:
            temperature (float): Sampling temperature for generation.
            settings (Settings | None): Optional settings override.
        Returns:
            Tuple[BaseChatModel, str]: Fallback chat model instance and model name.
        """
        cfg = settings or get_settings()
        if not cfg.gemini_api_key:
            raise ValueError("GEMINI_API_KEY must be configured when using the Gemini backend.")
        fallback_name = cfg.gemini_fallback_model
        model = ChatGoogleGenerativeAI(
            model=fallback_name,
            google_api_key=cfg.gemini_api_key,
            temperature=temperature,
            timeout=30.0,
            max_retries=2,
        )
        return model, fallback_name

