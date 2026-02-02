"""OpenAI API client for embeddings and chat completions."""
import logging
import os
from typing import List, Optional

logger = logging.getLogger(__name__)

# Lazy client so we don't fail at import if key is missing
_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    try:
        from openai import OpenAI
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            logger.debug("OPENAI_API_KEY not set; AI features disabled")
            return None
        _client = OpenAI(api_key=api_key)
        return _client
    except Exception as e:
        logger.debug(f"OpenAI client not available: {e}")
        return None


def is_available() -> bool:
    """Return True if OpenAI API is configured and usable."""
    return _get_client() is not None


def get_embeddings(texts: List[str], model: str = "text-embedding-3-small") -> Optional[List[List[float]]]:
    """
    Get embedding vectors for a list of texts.
    
    Args:
        texts: List of strings to embed
        model: Embedding model name (default: text-embedding-3-small)
        
    Returns:
        List of embedding vectors (each a list of floats), or None if API unavailable/failed
    """
    client = _get_client()
    if not client or not texts:
        return None
    try:
        response = client.embeddings.create(input=texts, model=model)
        # Preserve order; response.data is in order
        return [item.embedding for item in response.data]
    except Exception as e:
        logger.warning(f"Embeddings API error: {e}")
        return None


def chat(
    prompt: str,
    system: Optional[str] = None,
    model: str = "gpt-4o-mini",
    max_tokens: int = 500,
) -> Optional[str]:
    """
    Send a single prompt and return the assistant reply.
    
    Args:
        prompt: User message
        system: Optional system message
        model: Model name (default: gpt-4o-mini)
        max_tokens: Max response length
        
    Returns:
        Reply text or None if API unavailable/failed
    """
    client = _get_client()
    if not client:
        return None
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
        )
        if response.choices and len(response.choices) > 0:
            return (response.choices[0].message.content or "").strip()
        return None
    except Exception as e:
        logger.warning(f"Chat API error: {e}")
        return None
