"""Story grouping logic to detect similar articles from multiple outlets."""
import re
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


class StoryGrouper:
    """Groups similar articles based on title similarity."""
    
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
    
    def group_stories(self, articles: List[Dict]) -> List[List[Dict]]:
        """
        Group articles into clusters based on title similarity.
        
        Args:
            articles: List of article dictionaries with 'title' key
            
        Returns:
            List of groups, where each group is a list of similar articles
        """
        if not articles:
            return []
        
        groups: List[List[Dict]] = []
        
        for article in articles:
            title = article.get('title', '')
            if not title:
                # Articles without titles go into their own group
                groups.append([article])
                continue
            
            # Find the best matching group
            best_group_idx = None
            best_similarity = 0.0
            
            for idx, group in enumerate(groups):
                # Check similarity against all articles in the group
                # Use the highest similarity found in the group
                max_similarity = 0.0
                for group_article in group:
                    group_title = group_article.get('title', '')
                    if group_title:
                        similarity = self.calculate_similarity(title, group_title)
                        max_similarity = max(max_similarity, similarity)
                
                if max_similarity > best_similarity:
                    best_similarity = max_similarity
                    best_group_idx = idx
            
            # Add to existing group if similarity is above threshold
            if best_group_idx is not None and best_similarity >= self.similarity_threshold:
                groups[best_group_idx].append(article)
                logger.debug(f"Added article to existing group (similarity: {best_similarity:.2f})")
            else:
                # Create new group
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
