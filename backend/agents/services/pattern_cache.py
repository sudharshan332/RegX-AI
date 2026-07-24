"""
Pattern caching system for RegX-AI agents.

Provides intelligent pattern matching and caching to minimize AI credit usage
by leveraging existing RDM patterns and analysis results.
"""

import json
import logging
import time
import re
import hashlib
from typing import Dict, List, Optional, Any, Set, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
import os

logger = logging.getLogger(__name__)


@dataclass
class PatternMatch:
    """Result of pattern matching operation."""
    pattern_id: str
    pattern_type: str  # simple, rdm, regex
    confidence: float
    description: str
    category: Optional[str] = None
    jira_link: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "pattern_type": self.pattern_type,
            "confidence": self.confidence,
            "description": self.description,
            "category": self.category,
            "jira_link": self.jira_link,
            "metadata": self.metadata
        }


@dataclass
class CachedAnalysis:
    """Cached analysis result."""
    test_signature: str
    pattern_match: PatternMatch
    full_analysis: Dict[str, Any]
    timestamp: float
    usage_count: int = 0
    last_used: float = field(default_factory=time.time)
    
    def is_expired(self, ttl_seconds: int) -> bool:
        """Check if cached analysis has expired."""
        return (time.time() - self.timestamp) > ttl_seconds
    
    def update_usage(self):
        """Update usage statistics."""
        self.usage_count += 1
        self.last_used = time.time()


class PatternCache:
    """
    Intelligent pattern matching and caching system.
    
    Provides multi-layer pattern matching:
    1. Simple status/category patterns
    2. RDM failure patterns (108+ predefined)
    3. Regex-based log patterns
    4. Cached analysis results
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.cache_ttl_hours = self.config.get("ttl_hours", 24)
        self.max_cache_entries = self.config.get("max_entries", 10000)
        
        # Pattern databases
        self.simple_patterns: Dict[str, PatternMatch] = {}
        self.rdm_patterns: Dict[str, PatternMatch] = {}
        self.regex_patterns: List[Tuple[re.Pattern, PatternMatch]] = []
        
        # Analysis cache
        self.analysis_cache: Dict[str, CachedAnalysis] = {}
        self.cache_stats = {
            "hits": 0,
            "misses": 0,
            "pattern_matches": 0,
            "cache_size": 0
        }
        
        # Load patterns from existing data
        self._load_rdm_patterns()
        self._load_simple_patterns()
        self._load_regex_patterns()
        
        logger.info(f"Pattern cache initialized with {len(self.rdm_patterns)} RDM patterns")
    
    def _load_rdm_patterns(self):
        """Load RDM failure patterns from existing data."""
        try:
            # Load from existing failed analysis data
            data_file = "/Users/sudharshan.musali/regx/RegX-AI/data/failed_analysis_central_regression_dry_run_cdp_11-jun-2026.json"
            
            if os.path.exists(data_file):
                with open(data_file, 'r') as f:
                    data = json.load(f)
                
                # Extract unique patterns
                seen_patterns = set()
                for item in data:
                    if item.get("pattern_matched") and item.get("pattern_description"):
                        pattern_desc = item["pattern_description"]
                        if pattern_desc not in seen_patterns:
                            seen_patterns.add(pattern_desc)
                            
                            pattern_id = self._generate_pattern_id(pattern_desc)
                            self.rdm_patterns[pattern_id] = PatternMatch(
                                pattern_id=pattern_id,
                                pattern_type="rdm",
                                confidence=0.95,
                                description=pattern_desc,
                                category=item.get("rdm_category", "PRODUCT"),
                                jira_link=item.get("pattern_jira", ""),
                                metadata={
                                    "rdm_resolution": item.get("rdm_resolution", ""),
                                    "generated_comment": item.get("generated_comment", "")
                                }
                            )
            
            # Add common RDM patterns
            self._add_common_rdm_patterns()
            
        except Exception as e:
            logger.error(f"Failed to load RDM patterns: {e}")
            self._add_common_rdm_patterns()  # Fallback to common patterns
    
    def _add_common_rdm_patterns(self):
        """Add common RDM failure patterns."""
        common_patterns = [
            {
                "description": "Resource allocation/provisioning failure - intermittent rerun",
                "category": "PRODUCT",
                "confidence": 0.95,
                "keywords": ["resource allocation", "provisioning failure", "timeout"]
            },
            {
                "description": "RDM deployment service unavailable",
                "category": "INFRASTRUCTURE",
                "confidence": 0.98,
                "keywords": ["deployment service", "unavailable", "connection refused"]
            },
            {
                "description": "Cluster configuration validation failed",
                "category": "INFRASTRUCTURE", 
                "confidence": 0.90,
                "keywords": ["configuration", "validation failed", "invalid config"]
            },
            {
                "description": "Host imaging timeout or failure",
                "category": "INFRASTRUCTURE",
                "confidence": 0.92,
                "keywords": ["imaging", "timeout", "host preparation"]
            },
            {
                "description": "Network connectivity issues during deployment",
                "category": "INFRASTRUCTURE",
                "confidence": 0.88,
                "keywords": ["network", "connectivity", "unreachable"]
            }
        ]
        
        for i, pattern in enumerate(common_patterns):
            pattern_id = f"rdm_common_{i:03d}"
            self.rdm_patterns[pattern_id] = PatternMatch(
                pattern_id=pattern_id,
                pattern_type="rdm",
                confidence=pattern["confidence"],
                description=pattern["description"],
                category=pattern["category"],
                metadata={"keywords": pattern["keywords"]}
            )
    
    def _load_simple_patterns(self):
        """Load simple status/category based patterns."""
        simple_patterns_data = [
            {
                "id": "rdm_deployment_skip",
                "description": "Test skipped due to RDM deployment failure",
                "category": "INFRASTRUCTURE",
                "confidence": 0.98,
                "conditions": {
                    "status": "skipped",
                    "failure_analysis.category": "DEVPROD_SERVICE:RDM"
                }
            },
            {
                "id": "test_failure_generic",
                "description": "Generic test failure requiring analysis",
                "category": "UNKNOWN",
                "confidence": 0.60,
                "conditions": {
                    "status": ["failed", "failure"]
                }
            },
            {
                "id": "timeout_failure",
                "description": "Test timeout failure",
                "category": "TEST_BUG",
                "confidence": 0.80,
                "conditions": {
                    "status": "failed",
                    "error_message": ["timeout", "timed out"]
                }
            }
        ]
        
        for pattern_data in simple_patterns_data:
            self.simple_patterns[pattern_data["id"]] = PatternMatch(
                pattern_id=pattern_data["id"],
                pattern_type="simple",
                confidence=pattern_data["confidence"],
                description=pattern_data["description"],
                category=pattern_data["category"],
                metadata={"conditions": pattern_data["conditions"]}
            )
    
    def _load_regex_patterns(self):
        """Load regex-based log patterns."""
        regex_patterns_data = [
            {
                "pattern": r"FATAL.*stargate.*cc:\d+",
                "description": "Stargate FATAL error",
                "category": "PRODUCT",
                "confidence": 0.85
            },
            {
                "pattern": r"ERROR.*curator.*failed",
                "description": "Curator operation failed", 
                "category": "PRODUCT",
                "confidence": 0.80
            },
            {
                "pattern": r"Connection refused.*port \d+",
                "description": "Service connection refused",
                "category": "INFRASTRUCTURE",
                "confidence": 0.75
            },
            {
                "pattern": r"TimeoutError.*\d+s",
                "description": "Operation timeout",
                "category": "TEST_BUG",
                "confidence": 0.70
            }
        ]
        
        for i, pattern_data in enumerate(regex_patterns_data):
            try:
                regex = re.compile(pattern_data["pattern"], re.IGNORECASE)
                pattern_match = PatternMatch(
                    pattern_id=f"regex_{i:03d}",
                    pattern_type="regex",
                    confidence=pattern_data["confidence"],
                    description=pattern_data["description"],
                    category=pattern_data["category"],
                    metadata={"regex": pattern_data["pattern"]}
                )
                self.regex_patterns.append((regex, pattern_match))
            except re.error as e:
                logger.warning(f"Invalid regex pattern '{pattern_data['pattern']}': {e}")
    
    def _generate_pattern_id(self, description: str) -> str:
        """Generate a unique pattern ID from description."""
        hash_obj = hashlib.md5(description.encode())
        return f"rdm_{hash_obj.hexdigest()[:8]}"
    
    def _generate_test_signature(self, test_result: Dict[str, Any]) -> str:
        """Generate a signature for test result for caching."""
        # Create signature from key fields
        signature_data = {
            "test_name": test_result.get("test_name", ""),
            "status": test_result.get("status", ""),
            "error_summary": test_result.get("error_summary", "")[:200],  # Truncate
            "failure_category": test_result.get("failure_analysis", {}).get("category", "")
        }
        
        signature_str = json.dumps(signature_data, sort_keys=True)
        return hashlib.md5(signature_str.encode()).hexdigest()
    
    async def find_cached_analysis(self, test_result: Dict[str, Any]) -> Optional[CachedAnalysis]:
        """Find cached analysis for test result."""
        signature = self._generate_test_signature(test_result)
        
        cached = self.analysis_cache.get(signature)
        if cached:
            ttl_seconds = self.cache_ttl_hours * 3600
            if not cached.is_expired(ttl_seconds):
                cached.update_usage()
                self.cache_stats["hits"] += 1
                return cached
            else:
                # Remove expired entry
                del self.analysis_cache[signature]
        
        self.cache_stats["misses"] += 1
        return None
    
    def cache_analysis(
        self, 
        test_result: Dict[str, Any], 
        pattern_match: PatternMatch,
        full_analysis: Dict[str, Any]
    ):
        """Cache analysis result for future use."""
        signature = self._generate_test_signature(test_result)
        
        # Check cache size limit
        if len(self.analysis_cache) >= self.max_cache_entries:
            self._evict_old_entries()
        
        cached_analysis = CachedAnalysis(
            test_signature=signature,
            pattern_match=pattern_match,
            full_analysis=full_analysis,
            timestamp=time.time()
        )
        
        self.analysis_cache[signature] = cached_analysis
        self.cache_stats["cache_size"] = len(self.analysis_cache)
    
    def _evict_old_entries(self):
        """Evict old cache entries to make room for new ones."""
        # Remove 10% of oldest entries
        entries_to_remove = max(1, self.max_cache_entries // 10)
        
        # Sort by last used time
        sorted_entries = sorted(
            self.analysis_cache.items(),
            key=lambda x: x[1].last_used
        )
        
        for i in range(min(entries_to_remove, len(sorted_entries))):
            signature = sorted_entries[i][0]
            del self.analysis_cache[signature]
    
    def match_simple_patterns(self, test_result: Dict[str, Any]) -> Optional[PatternMatch]:
        """Match against simple status/category patterns."""
        for pattern_id, pattern in self.simple_patterns.items():
            if self._matches_simple_pattern(test_result, pattern):
                self.cache_stats["pattern_matches"] += 1
                logger.debug(f"Simple pattern match: {pattern_id}")
                return pattern
        return None
    
    def _matches_simple_pattern(self, test_result: Dict[str, Any], pattern: PatternMatch) -> bool:
        """Check if test result matches a simple pattern."""
        conditions = pattern.metadata.get("conditions", {})
        
        for field, expected_values in conditions.items():
            # Handle nested fields like failure_analysis.category
            if "." in field:
                parts = field.split(".")
                value = test_result
                for part in parts:
                    value = value.get(part, {}) if isinstance(value, dict) else {}
                actual_value = value if not isinstance(value, dict) else ""
            else:
                actual_value = test_result.get(field, "")
            
            # Check if value matches
            if isinstance(expected_values, list):
                if actual_value not in expected_values:
                    return False
            else:
                if actual_value != expected_values:
                    return False
        
        return True
    
    def match_rdm_patterns(self, test_result: Dict[str, Any]) -> Optional[PatternMatch]:
        """Match against RDM failure patterns."""
        # Check if already pattern matched
        if test_result.get("pattern_matched"):
            pattern_desc = test_result.get("pattern_description", "")
            for pattern in self.rdm_patterns.values():
                if pattern.description == pattern_desc:
                    self.cache_stats["pattern_matches"] += 1
                    logger.debug(f"RDM pattern match: {pattern.pattern_id}")
                    return pattern
        
        # Check against keywords in error messages
        error_text = self._extract_error_text(test_result).lower()
        if error_text:
            for pattern in self.rdm_patterns.values():
                keywords = pattern.metadata.get("keywords", [])
                if keywords and self._text_contains_keywords(error_text, keywords):
                    # Lower confidence for keyword matching
                    pattern_copy = PatternMatch(
                        pattern_id=pattern.pattern_id,
                        pattern_type=pattern.pattern_type,
                        confidence=max(0.6, pattern.confidence - 0.2),
                        description=pattern.description,
                        category=pattern.category,
                        jira_link=pattern.jira_link,
                        metadata=pattern.metadata
                    )
                    self.cache_stats["pattern_matches"] += 1
                    logger.debug(f"RDM keyword match: {pattern.pattern_id}")
                    return pattern_copy
        
        return None
    
    def _extract_error_text(self, test_result: Dict[str, Any]) -> str:
        """Extract error text from test result for pattern matching."""
        error_fields = [
            "error_message",
            "error_summary", 
            "exception_summary",
            "failure_reason"
        ]
        
        error_text = ""
        for field in error_fields:
            value = test_result.get(field, "")
            if value:
                error_text += " " + str(value)
        
        return error_text.strip()
    
    def _text_contains_keywords(self, text: str, keywords: List[str]) -> bool:
        """Check if text contains any of the keywords."""
        text_lower = text.lower()
        return any(keyword.lower() in text_lower for keyword in keywords)
    
    def match_regex_patterns(self, test_result: Dict[str, Any]) -> Optional[PatternMatch]:
        """Match against regex log patterns."""
        error_text = self._extract_error_text(test_result)
        if not error_text:
            return None
        
        for regex, pattern in self.regex_patterns:
            if regex.search(error_text):
                self.cache_stats["pattern_matches"] += 1
                logger.debug(f"Regex pattern match: {pattern.pattern_id}")
                return pattern
        
        return None
    
    def find_best_pattern_match(
        self, 
        test_result: Dict[str, Any],
        min_confidence: float = 0.5
    ) -> Optional[PatternMatch]:
        """
        Find the best pattern match using all available pattern types.
        
        Args:
            test_result: Test result data
            min_confidence: Minimum confidence threshold
            
        Returns:
            Best matching pattern or None
        """
        matches = []
        
        # Try simple patterns first (highest confidence)
        simple_match = self.match_simple_patterns(test_result)
        if simple_match and simple_match.confidence >= min_confidence:
            matches.append(simple_match)
        
        # Try RDM patterns
        rdm_match = self.match_rdm_patterns(test_result)
        if rdm_match and rdm_match.confidence >= min_confidence:
            matches.append(rdm_match)
        
        # Try regex patterns
        regex_match = self.match_regex_patterns(test_result)
        if regex_match and regex_match.confidence >= min_confidence:
            matches.append(regex_match)
        
        # Return highest confidence match
        if matches:
            best_match = max(matches, key=lambda m: m.confidence)
            logger.info(f"Best pattern match: {best_match.pattern_id} (confidence: {best_match.confidence:.2f})")
            return best_match
        
        return None
    
    def get_pattern_stats(self) -> Dict[str, Any]:
        """Get pattern matching statistics."""
        total_patterns = (
            len(self.simple_patterns) + 
            len(self.rdm_patterns) + 
            len(self.regex_patterns)
        )
        
        return {
            "total_patterns": total_patterns,
            "simple_patterns": len(self.simple_patterns),
            "rdm_patterns": len(self.rdm_patterns), 
            "regex_patterns": len(self.regex_patterns),
            "cache_stats": self.cache_stats.copy(),
            "cache_hit_rate": (
                self.cache_stats["hits"] / 
                max(1, self.cache_stats["hits"] + self.cache_stats["misses"])
            ),
            "pattern_match_rate": (
                self.cache_stats["pattern_matches"] / 
                max(1, self.cache_stats["hits"] + self.cache_stats["misses"])
            )
        }
    
    def clear_cache(self):
        """Clear the analysis cache."""
        self.analysis_cache.clear()
        self.cache_stats["cache_size"] = 0
        logger.info("Pattern cache cleared")
    
    def get_pattern_by_id(self, pattern_id: str) -> Optional[PatternMatch]:
        """Get pattern by ID from all pattern databases."""
        # Check simple patterns
        if pattern_id in self.simple_patterns:
            return self.simple_patterns[pattern_id]
        
        # Check RDM patterns
        if pattern_id in self.rdm_patterns:
            return self.rdm_patterns[pattern_id]
        
        # Check regex patterns
        for _, pattern in self.regex_patterns:
            if pattern.pattern_id == pattern_id:
                return pattern
        
        return None