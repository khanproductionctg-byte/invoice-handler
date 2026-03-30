"""
Embedding utilities for text vectorization using sentence transformers.
"""
import os
import json
import hashlib
import logging
from typing import List, Union, Optional
import numpy as np
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

_model = None
_model_name = "sentence-transformers/all-MiniLM-L6-v2"

_redis_client = None

def get_redis_client():
    """Get or create Redis client for caching."""
    global _redis_client
    if _redis_client is None:
        try:
            import redis
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
            _redis_client = redis.from_url(redis_url, decode_responses=False)
            _redis_client.ping()
            logger.info(f"Redis caching enabled: {redis_url}")
        except Exception as e:
            logger.warning(f"Redis unavailable, using in-memory cache only: {e}")
            _redis_client = None
    return _redis_client

def _get_cache_key(text: str) -> str:
    """Generate cache key for embedding."""
    text_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
    return f"embedding:{_model_name}:{text_hash}"

def _get_embedding_cached(text: str) -> Optional[List[float]]:
    """Get embedding from cache if available."""
    redis = get_redis_client()
    if redis is None:
        return None
    try:
        cache_key = _get_cache_key(text)
        cached = redis.get(cache_key)
        if cached:
            logger.debug(f"Embedding cache hit: {cache_key[:30]}...")
            return json.loads(cached.decode() if isinstance(cached, bytes) else cached)
    except Exception as e:
        logger.warning(f"Cache read error: {e}")
    return None

def _set_embedding_cached(text: str, embedding: List[float], ttl: int = 86400):
    """Store embedding in cache."""
    redis = get_redis_client()
    if redis is None:
        return
    try:
        cache_key = _get_cache_key(text)
        redis.setex(cache_key, ttl, json.dumps(embedding))
        logger.debug(f"Embedding cached: {cache_key[:30]}...")
    except Exception as e:
        logger.warning(f"Cache write error: {e}")


def get_embedding_model() -> SentenceTransformer:
    """
    Get or load the sentence transformer model for embeddings.

    Returns:
        SentenceTransformer model instance
    """
    global _model
    if _model is None:
        logger.info(f"Loading embedding model: {_model_name}")
        _model = SentenceTransformer(_model_name)
    return _model


def get_embedding(text: Union[str, List[str]]) -> List[float]:
    """
    Generate embedding vector for text with Redis caching.

    Args:
        text: Input text or list of texts

    Returns:
        Embedding vector as list of floats (384 dimensions for all-MiniLM-L6-v2)
    """
    try:
        if isinstance(text, str):
            cached = _get_embedding_cached(text)
            if cached is not None:
                return cached
            
            model = get_embedding_model()
            embeddings = model.encode([text])
            embedding = embeddings[0].tolist()
            _set_embedding_cached(text, embedding)
            return embedding
        else:
            uncached_texts = []
            uncached_indices = []
            results = [None] * len(texts := text)
            
            for i, t in enumerate(texts):
                cached = _get_embedding_cached(t)
                if cached is not None:
                    results[i] = cached
                else:
                    uncached_texts.append(t)
                    uncached_indices.append(i)
            
            if uncached_texts:
                model = get_embedding_model()
                new_embeddings = model.encode(uncached_texts)
                for idx, emb in zip(uncached_indices, new_embeddings):
                    embedding_list = emb.tolist()
                    results[idx] = embedding_list
                    _set_embedding_cached(texts[idx], embedding_list)
            
            return results
            
    except Exception as e:
        logger.error(f"Failed to generate embedding: {str(e)}")
        if isinstance(text, str):
            return [0.0] * 384
        else:
            return [[0.0] * 384 for _ in text]


def get_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """
    Batch embed multiple texts at once for better performance.
    
    Args:
        texts: List of input texts
        
    Returns:
        List of embedding vectors
    """
    if not texts:
        return []
    return get_embedding(texts)


def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """
    Calculate cosine similarity between two vectors.

    Args:
        vec1: First vector
        vec2: Second vector

    Returns:
        Cosine similarity score between -1 and 1
    """
    try:
        # Convert to numpy arrays
        a = np.array(vec1)
        b = np.array(vec2)
        
        # Calculate cosine similarity
        dot_product = np.dot(a, b)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        
        if norm_a == 0 or norm_b == 0:
            return 0.0
            
        return dot_product / (norm_a * norm_b)
    except Exception as e:
        logger.error(f"Failed to calculate cosine similarity: {str(e)}")
        return 0.0


def find_most_similar(
    query_embedding: List[float], 
    candidate_embeddings: List[List[float]], 
    top_k: int = 5
) -> List[tuple]:
    """
    Find most similar embeddings to a query embedding.

    Args:
        query_embedding: Query vector
        candidate_embeddings: List of candidate vectors
        top_k: Number of top results to return

    Returns:
        List of tuples (index, similarity_score) sorted by similarity descending
    """
    try:
        similarities = []
        for i, candidate in enumerate(candidate_embeddings):
            similarity = cosine_similarity(query_embedding, candidate)
            similarities.append((i, similarity))
        
        # Sort by similarity descending
        similarities.sort(key=lambda x: x[1], reverse=True)
        
        # Return top k
        return similarities[:top_k]
    except Exception as e:
        logger.error(f"Failed to find most similar: {str(e)}")
        return []