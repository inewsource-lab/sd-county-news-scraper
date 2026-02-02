"""Story grouping logic to detect similar articles from multiple outlets."""
import re
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """Cosine similarity between two vectors. Returns 0.0 if invalid."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class StoryGrouper:
    """Groups similar articles based on title (and optionally embedding) similarity."""
    
    def __init__(self, similarity_threshold: float = 0.6):
        """
        Initialize story grouper.
        
        Args:
            similarity_threshold: Minimum similarity score (0.0-1.0) to group articles
        """
        self.similarity_threshold = similarity_threshold
    
    def calculate_similarity(self, title1: str, title2: str) -> float:
        """
        Calculate similarity score between two titles using Jaccard similarity.
        
        Args:
            title1: First article title
            title2: Second article title
            
        Returns:
            Similarity score between 0.0 and 1.0
        """
        # Normalize: lowercase, remove punctuation, split into words
        words1 = set(re.findall(r'\w+', title1.lower()))
        words2 = set(re.findall(r'\w+', title2.lower()))
        
        # Remove common stop words that don't add meaning
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'been', 'be', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might', 'must', 'can'}
        words1 = words1 - stop_words
        words2 = words2 - stop_words
        
        # Skip if both are empty after removing stop words
        if not words1 and not words2:
            return 1.0
        if not words1 or not words2:
            return 0.0
        
        # Jaccard similarity: intersection / union
        intersection = len(words1 & words2)
        union = len(words1 | words2)
        
        similarity = intersection / union if union > 0 else 0.0
        
        logger.debug(f"Similarity between '{title1[:50]}...' and '{title2[:50]}...': {similarity:.2f}")
        
        return similarity
    
    def _similarity(
        self,
        article: Dict,
        group_article: Dict,
        embedding_vectors: Optional[List[List[float]]] = None,
        article_idx: Optional[int] = None,
        group_article_idx_in_flat: Optional[Dict] = None,
    ) -> float:
        """Return similarity between article and group_article; use embeddings if provided."""
        if embedding_vectors is not None and article_idx is not None and group_article_idx_in_flat is not None:
            idx2 = group_article_idx_in_flat.get(id(group_article))
            if idx2 is not None:
                v1 = embedding_vectors[article_idx]
                v2 = embedding_vectors[idx2]
                if v1 and v2:
                    return _cosine_similarity(v1, v2)
        title = article.get('title', '')
        group_title = group_article.get('title', '')
        if title and group_title:
            return self.calculate_similarity(title, group_title)
        return 0.0

    def group_stories(
        self,
        articles: List[Dict],
        embedding_vectors: Optional[List[List[float]]] = None,
    ) -> List[List[Dict]]:
        """
        Group articles into clusters based on title or embedding similarity.
        
        Args:
            articles: List of article dictionaries with 'title' key
            embedding_vectors: Optional list of embedding vectors (same order as articles);
                when provided, cosine similarity is used instead of Jaccard on titles
            
        Returns:
            List of groups, where each group is a list of similar articles
        """
        if not articles:
            return []
        
        # Build flat index: article id -> index (for embedding lookup)
        article_to_idx = {id(a): i for i, a in enumerate(articles)}
        use_embeddings = (
            embedding_vectors is not None
            and len(embedding_vectors) == len(articles)
        )
        
        groups: List[List[Dict]] = []
        
        for i, article in enumerate(articles):
            title = article.get('title', '')
            if not title and not use_embeddings:
                groups.append([article])
                continue
            
            best_group_idx = None
            best_similarity = 0.0
            
            for idx, group in enumerate(groups):
                max_similarity = 0.0
                for group_article in group:
                    if use_embeddings and embedding_vectors:
                        sim = self._similarity(
                            article,
                            group_article,
                            embedding_vectors=embedding_vectors,
                            article_idx=i,
                            group_article_idx_in_flat=article_to_idx,
                        )
                    else:
                        sim = self._similarity(article, group_article)
                    max_similarity = max(max_similarity, sim)
                
                if max_similarity > best_similarity:
                    best_similarity = max_similarity
                    best_group_idx = idx
            
            if best_group_idx is not None and best_similarity >= self.similarity_threshold:
                groups[best_group_idx].append(article)
                logger.debug(f"Added article to existing group (similarity: {best_similarity:.2f})")
            else:
                groups.append([article])
                logger.debug(f"Created new group for article")
        
        # Sort groups: priority sources first, then by publication time (most recent first)
        for group in groups:
            def sort_key(a):
                pub_dt = a.get('pub_datetime')
                # Priority sources first, then articles with dates, then by timestamp (most recent first)
                return (
                    not a.get('is_priority', False),  # Priority sources first (False sorts before True)
                    pub_dt is None,  # Articles with dates first
                    -pub_dt.timestamp() if pub_dt else 0  # Most recent first (negative for descending)
                )
            group.sort(key=sort_key)
        
        logger.info(f"Grouped {len(articles)} articles into {len(groups)} groups")
        
        return groups
