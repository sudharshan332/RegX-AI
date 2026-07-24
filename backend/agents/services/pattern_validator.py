"""
Pattern Validation Service for RegX-AI Agent Framework

This service validates pattern syntax, tests patterns against historical data,
and tracks pattern effectiveness to ensure high-quality pattern database.
"""

import re
import json
import logging
import asyncio
import time
from typing import Dict, List, Optional, Any, Tuple, Set
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
import statistics

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of pattern validation."""
    is_valid: bool
    confidence: float
    issues: List[str]
    warnings: List[str]
    suggestions: List[str]
    test_results: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class TestResult:
    """Result of testing pattern against historical data."""
    total_tests: int
    matches: int
    correct_matches: int
    false_positives: int
    false_negatives: int
    accuracy: float
    precision: float
    recall: float
    f1_score: float
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class EffectivenessMetrics:
    """Pattern effectiveness metrics over time."""
    pattern_id: str
    creation_date: str
    total_applications: int
    successful_matches: int
    false_positives: int
    user_corrections: int
    confidence_trend: List[float]
    usage_frequency: float
    effectiveness_score: float
    recommendation: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


class PatternValidator:
    """Service for validating and testing patterns."""
    
    def __init__(self):
        # Validation thresholds
        self.min_confidence = 0.6
        self.min_accuracy = 0.7
        self.min_precision = 0.75
        self.max_false_positive_rate = 0.2
        
        # Pattern complexity limits
        self.max_regex_length = 500
        self.max_alternations = 10
        self.max_nested_groups = 5
        
        # Historical data for testing
        self.test_data_cache = {}
        self.cache_ttl = 3600  # 1 hour
    
    def validate_pattern_syntax(self, pattern: Dict[str, Any]) -> ValidationResult:
        """
        Validate regex syntax and pattern structure.
        
        Args:
            pattern: Pattern dictionary with regex, description, etc.
            
        Returns:
            ValidationResult with validation details
        """
        issues = []
        warnings = []
        suggestions = []
        confidence = 1.0
        
        try:
            # Basic structure validation
            required_fields = ["id", "regex", "confidence", "category", "description"]
            missing_fields = [field for field in required_fields if field not in pattern or not pattern[field]]
            
            if missing_fields:
                issues.extend([f"Missing required field: {field}" for field in missing_fields])
                confidence -= 0.2 * len(missing_fields)
            
            # Regex syntax validation
            regex = pattern.get("regex", "")
            if not regex:
                issues.append("Empty regex pattern")
                confidence = 0.0
            else:
                try:
                    compiled_pattern = re.compile(regex)
                    
                    # Check pattern complexity
                    complexity_issues = self._check_pattern_complexity(regex)
                    if complexity_issues:
                        warnings.extend(complexity_issues)
                        confidence -= 0.1
                    
                    # Check for common issues
                    pattern_issues = self._check_common_pattern_issues(regex)
                    if pattern_issues:
                        warnings.extend(pattern_issues)
                        confidence -= 0.05 * len(pattern_issues)
                    
                    # Performance warnings
                    performance_warnings = self._check_performance_issues(regex)
                    if performance_warnings:
                        warnings.extend(performance_warnings)
                        confidence -= 0.05
                    
                except re.error as e:
                    issues.append(f"Invalid regex syntax: {str(e)}")
                    confidence = 0.0
            
            # Confidence score validation
            pattern_confidence = pattern.get("confidence", 0.0)
            if not isinstance(pattern_confidence, (int, float)) or not 0.0 <= pattern_confidence <= 1.0:
                issues.append("Pattern confidence must be a number between 0.0 and 1.0")
                confidence -= 0.1
            elif pattern_confidence < self.min_confidence:
                warnings.append(f"Pattern confidence ({pattern_confidence:.2f}) below recommended minimum ({self.min_confidence})")
                confidence -= 0.1
            
            # Category validation
            valid_categories = [
                "INTERMITTENT", "INFRA_INTERMITTENT", "INFRA_RESOURCE", 
                "INFRA_NODE", "INFRA_BUG", "KNOWN_ISSUE"
            ]
            category = pattern.get("category", "")
            if category not in valid_categories:
                warnings.append(f"Unknown category '{category}', consider using one of: {', '.join(valid_categories)}")
            
            # Description quality check
            description = pattern.get("description", "")
            if len(description) < 20:
                warnings.append("Pattern description is too brief, consider adding more detail")
            elif len(description) > 200:
                warnings.append("Pattern description is very long, consider making it more concise")
            
            # Generate suggestions
            if confidence < 0.8:
                suggestions.extend(self._generate_improvement_suggestions(pattern, issues, warnings))
            
            is_valid = len(issues) == 0 and confidence >= 0.5
            
        except Exception as e:
            logger.error(f"Error validating pattern: {str(e)}")
            issues.append(f"Validation error: {str(e)}")
            confidence = 0.0
            is_valid = False
        
        return ValidationResult(
            is_valid=is_valid,
            confidence=max(confidence, 0.0),
            issues=issues,
            warnings=warnings,
            suggestions=suggestions
        )
    
    async def test_pattern_against_history(
        self, 
        pattern: Dict[str, Any], 
        test_data: Optional[List[Dict[str, Any]]] = None
    ) -> TestResult:
        """
        Test pattern against historical test failure data.
        
        Args:
            pattern: Pattern to test
            test_data: Optional historical test data, will load if not provided
            
        Returns:
            TestResult with accuracy metrics
        """
        try:
            if not test_data:
                test_data = await self._load_historical_test_data(pattern.get("pattern_type", "intermittent"))
            
            if not test_data:
                logger.warning("No historical test data available for pattern testing")
                return TestResult(
                    total_tests=0, matches=0, correct_matches=0, false_positives=0,
                    false_negatives=0, accuracy=0.0, precision=0.0, recall=0.0, f1_score=0.0
                )
            
            regex = pattern.get("regex", "")
            if not regex:
                raise ValueError("Pattern has no regex")
            
            compiled_pattern = re.compile(regex, re.IGNORECASE)
            
            # Test against historical data
            matches = 0
            correct_matches = 0
            false_positives = 0
            false_negatives = 0
            
            for test_case in test_data:
                error_message = test_case.get("error_message", "")
                expected_match = test_case.get("should_match", False)
                
                actual_match = bool(compiled_pattern.search(error_message))
                
                if actual_match:
                    matches += 1
                    if expected_match:
                        correct_matches += 1
                    else:
                        false_positives += 1
                else:
                    if expected_match:
                        false_negatives += 1
            
            total_tests = len(test_data)
            
            # Calculate metrics
            accuracy = (correct_matches + (total_tests - matches - false_negatives)) / total_tests if total_tests > 0 else 0.0
            precision = correct_matches / matches if matches > 0 else 0.0
            recall = correct_matches / (correct_matches + false_negatives) if (correct_matches + false_negatives) > 0 else 0.0
            f1_score = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
            
            return TestResult(
                total_tests=total_tests,
                matches=matches,
                correct_matches=correct_matches,
                false_positives=false_positives,
                false_negatives=false_negatives,
                accuracy=accuracy,
                precision=precision,
                recall=recall,
                f1_score=f1_score
            )
            
        except Exception as e:
            logger.error(f"Error testing pattern against history: {str(e)}")
            return TestResult(
                total_tests=0, matches=0, correct_matches=0, false_positives=0,
                false_negatives=0, accuracy=0.0, precision=0.0, recall=0.0, f1_score=0.0
            )
    
    def calculate_pattern_effectiveness(
        self, 
        pattern_id: str, 
        usage_history: List[Dict[str, Any]]
    ) -> EffectivenessMetrics:
        """
        Calculate comprehensive effectiveness metrics for a pattern.
        
        Args:
            pattern_id: ID of the pattern to analyze
            usage_history: Historical usage data for the pattern
            
        Returns:
            EffectivenessMetrics with comprehensive analysis
        """
        if not usage_history:
            return EffectivenessMetrics(
                pattern_id=pattern_id,
                creation_date=datetime.utcnow().isoformat(),
                total_applications=0,
                successful_matches=0,
                false_positives=0,
                user_corrections=0,
                confidence_trend=[],
                usage_frequency=0.0,
                effectiveness_score=0.0,
                recommendation="Insufficient data for analysis"
            )
        
        # Analyze usage history
        total_applications = len(usage_history)
        successful_matches = sum(1 for entry in usage_history if entry.get("correct", False))
        false_positives = sum(1 for entry in usage_history if entry.get("correct") is False)
        user_corrections = sum(1 for entry in usage_history if entry.get("user_corrected", False))
        
        # Calculate confidence trend
        confidence_trend = []
        for entry in usage_history:
            if "confidence" in entry:
                confidence_trend.append(entry["confidence"])
        
        # Calculate usage frequency (applications per day)
        if usage_history:
            first_usage = min(entry.get("timestamp", time.time()) for entry in usage_history)
            last_usage = max(entry.get("timestamp", time.time()) for entry in usage_history)
            days_active = max((last_usage - first_usage) / 86400, 1)  # At least 1 day
            usage_frequency = total_applications / days_active
        else:
            usage_frequency = 0.0
        
        # Calculate overall effectiveness score
        effectiveness_score = self._calculate_effectiveness_score(
            successful_matches, false_positives, user_corrections, total_applications, confidence_trend
        )
        
        # Generate recommendation
        recommendation = self._generate_effectiveness_recommendation(
            effectiveness_score, usage_frequency, false_positives, total_applications
        )
        
        creation_date = usage_history[0].get("timestamp", time.time()) if usage_history else time.time()
        
        return EffectivenessMetrics(
            pattern_id=pattern_id,
            creation_date=datetime.fromtimestamp(creation_date).isoformat(),
            total_applications=total_applications,
            successful_matches=successful_matches,
            false_positives=false_positives,
            user_corrections=user_corrections,
            confidence_trend=confidence_trend,
            usage_frequency=usage_frequency,
            effectiveness_score=effectiveness_score,
            recommendation=recommendation
        )
    
    def validate_and_test_pattern(
        self, 
        pattern: Dict[str, Any],
        test_data: Optional[List[Dict[str, Any]]] = None
    ) -> ValidationResult:
        """
        Perform comprehensive pattern validation including historical testing.
        
        Args:
            pattern: Pattern to validate and test
            test_data: Optional test data for validation
            
        Returns:
            ValidationResult with test results included
        """
        # Basic syntax validation
        validation_result = self.validate_pattern_syntax(pattern)
        
        if not validation_result.is_valid:
            return validation_result
        
        try:
            # Test against historical data
            test_result = asyncio.run(self.test_pattern_against_history(pattern, test_data))
            
            # Update validation based on test results
            if test_result.accuracy < self.min_accuracy:
                validation_result.warnings.append(f"Pattern accuracy ({test_result.accuracy:.2f}) below threshold ({self.min_accuracy})")
                validation_result.confidence *= 0.8
            
            if test_result.precision < self.min_precision:
                validation_result.warnings.append(f"Pattern precision ({test_result.precision:.2f}) below threshold ({self.min_precision})")
                validation_result.confidence *= 0.9
            
            false_positive_rate = test_result.false_positives / test_result.total_tests if test_result.total_tests > 0 else 0
            if false_positive_rate > self.max_false_positive_rate:
                validation_result.warnings.append(f"High false positive rate ({false_positive_rate:.2f})")
                validation_result.confidence *= 0.85
            
            # Add test results
            validation_result.test_results = test_result.to_dict()
            
            # Update suggestions based on test results
            if test_result.precision < 0.8 and test_result.false_positives > 0:
                validation_result.suggestions.append("Consider making the pattern more specific to reduce false positives")
            
            if test_result.recall < 0.7 and test_result.false_negatives > 0:
                validation_result.suggestions.append("Consider making the pattern more general to catch more cases")
            
        except Exception as e:
            logger.error(f"Error during pattern testing: {str(e)}")
            validation_result.warnings.append(f"Could not test pattern against historical data: {str(e)}")
        
        return validation_result
    
    def _check_pattern_complexity(self, regex: str) -> List[str]:
        """Check if pattern is overly complex."""
        issues = []
        
        if len(regex) > self.max_regex_length:
            issues.append(f"Pattern is very long ({len(regex)} chars), consider simplifying")
        
        # Count alternations (|)
        alternations = regex.count('|')
        if alternations > self.max_alternations:
            issues.append(f"Too many alternations ({alternations}), may impact performance")
        
        # Count nested groups
        open_parens = 0
        max_nesting = 0
        for char in regex:
            if char == '(':
                open_parens += 1
                max_nesting = max(max_nesting, open_parens)
            elif char == ')':
                open_parens -= 1
        
        if max_nesting > self.max_nested_groups:
            issues.append(f"Deep nesting detected ({max_nesting} levels), consider restructuring")
        
        return issues
    
    def _check_common_pattern_issues(self, regex: str) -> List[str]:
        """Check for common regex issues."""
        warnings = []
        
        # Unescaped dots that might be intended as literal dots
        if '.' in regex and r'\.' not in regex:
            warnings.append("Contains unescaped dots (.) - ensure they're intended as wildcards")
        
        # Potentially problematic quantifiers
        if re.search(r'\*\*|\+\+|\?\?', regex):
            warnings.append("Contains potentially problematic nested quantifiers")
        
        # Very broad patterns
        if regex.count('.*') > 2:
            warnings.append("Pattern contains many .* wildcards, may be too broad")
        
        # Check for anchoring
        if not (regex.startswith('^') or regex.endswith('$')):
            warnings.append("Consider anchoring pattern with ^ or $ for more precise matching")
        
        # Check for case sensitivity issues
        if re.search(r'[A-Z]', regex) and re.search(r'[a-z]', regex):
            warnings.append("Pattern contains mixed case - ensure case-insensitive matching is intended")
        
        return warnings
    
    def _check_performance_issues(self, regex: str) -> List[str]:
        """Check for potential performance issues."""
        warnings = []
        
        # Catastrophic backtracking patterns
        problematic_patterns = [
            r'\([^)]*\*[^)]*\*[^)]*\)',  # Nested quantifiers in groups
            r'\*.*\*',  # Multiple wildcards
            r'\+.*\+',  # Multiple plus quantifiers
        ]
        
        for pattern in problematic_patterns:
            if re.search(pattern, regex):
                warnings.append("Pattern may cause performance issues due to backtracking")
                break
        
        return warnings
    
    def _generate_improvement_suggestions(
        self, 
        pattern: Dict[str, Any], 
        issues: List[str], 
        warnings: List[str]
    ) -> List[str]:
        """Generate suggestions for pattern improvement."""
        suggestions = []
        
        if any("regex syntax" in issue.lower() for issue in issues):
            suggestions.append("Test regex pattern in a regex validator before submission")
        
        if any("confidence" in warning.lower() for warning in warnings):
            suggestions.append("Increase pattern confidence by adding more specific matching criteria")
        
        if any("description" in warning.lower() for warning in warnings):
            suggestions.append("Provide a detailed description explaining when and why this pattern should match")
        
        if any("performance" in warning.lower() for warning in warnings):
            suggestions.append("Optimize regex for better performance by reducing backtracking")
        
        if len(warnings) > 3:
            suggestions.append("Consider simplifying the pattern to reduce complexity")
        
        return suggestions
    
    async def _load_historical_test_data(self, pattern_type: str) -> List[Dict[str, Any]]:
        """Load historical test data for pattern validation."""
        cache_key = f"test_data_{pattern_type}"
        
        # Check cache first
        if cache_key in self.test_data_cache:
            cached_data, timestamp = self.test_data_cache[cache_key]
            if time.time() - timestamp < self.cache_ttl:
                return cached_data
        
        try:
            # In a real implementation, this would load from a database or file
            # For now, we'll return a simple mock dataset
            test_data = [
                {
                    "error_message": "Timedout executing command source cluster start in 300 secs with error:",
                    "should_match": True,
                    "pattern_type": "intermittent"
                },
                {
                    "error_message": "Connection refused to 10.1.1.1:22",
                    "should_match": True, 
                    "pattern_type": "intermittent"
                },
                {
                    "error_message": "Test completed successfully",
                    "should_match": False,
                    "pattern_type": "intermittent"
                }
            ]
            
            # Filter by pattern type
            filtered_data = [item for item in test_data if item.get("pattern_type") == pattern_type]
            
            # Cache the result
            self.test_data_cache[cache_key] = (filtered_data, time.time())
            
            return filtered_data
            
        except Exception as e:
            logger.error(f"Error loading historical test data: {str(e)}")
            return []
    
    def _calculate_effectiveness_score(
        self, 
        successful_matches: int, 
        false_positives: int, 
        user_corrections: int, 
        total_applications: int,
        confidence_trend: List[float]
    ) -> float:
        """Calculate overall effectiveness score for a pattern."""
        if total_applications == 0:
            return 0.0
        
        # Base accuracy score
        accuracy = successful_matches / total_applications
        
        # Penalty for false positives
        false_positive_penalty = false_positives / total_applications * 0.5
        
        # Penalty for user corrections
        correction_penalty = user_corrections / total_applications * 0.3
        
        # Confidence trend bonus (improving confidence over time)
        trend_bonus = 0.0
        if len(confidence_trend) > 1:
            trend_slope = (confidence_trend[-1] - confidence_trend[0]) / len(confidence_trend)
            trend_bonus = max(trend_slope * 0.1, -0.1)  # Cap at ±0.1
        
        # Calculate final score
        effectiveness_score = accuracy - false_positive_penalty - correction_penalty + trend_bonus
        
        return max(min(effectiveness_score, 1.0), 0.0)
    
    def _generate_effectiveness_recommendation(
        self,
        effectiveness_score: float,
        usage_frequency: float, 
        false_positives: int,
        total_applications: int
    ) -> str:
        """Generate recommendation based on effectiveness metrics."""
        if effectiveness_score >= 0.9:
            return "Excellent pattern - keep using"
        elif effectiveness_score >= 0.7:
            return "Good pattern - monitor for continued effectiveness"
        elif effectiveness_score >= 0.5:
            if false_positives > total_applications * 0.2:
                return "Pattern needs refinement - too many false positives"
            else:
                return "Pattern shows mixed results - consider improvements"
        else:
            if usage_frequency < 0.1:  # Less than once per 10 days
                return "Pattern rarely used and low effectiveness - consider removal"
            else:
                return "Pattern ineffective - needs significant revision or removal"


# Utility functions for agent integration

def validate_pattern(pattern: Dict[str, Any]) -> ValidationResult:
    """
    Convenience function to validate a pattern.
    
    Usage:
        result = validate_pattern(pattern_dict)
        if result.is_valid:
            # Pattern is valid
    """
    validator = PatternValidator()
    return validator.validate_pattern_syntax(pattern)


async def test_pattern_effectiveness(
    pattern: Dict[str, Any],
    test_data: Optional[List[Dict[str, Any]]] = None
) -> TestResult:
    """
    Convenience function to test pattern effectiveness.
    
    Usage:
        test_result = await test_pattern_effectiveness(pattern_dict)
        if test_result.accuracy > 0.8:
            # Pattern is effective
    """
    validator = PatternValidator()
    return await validator.test_pattern_against_history(pattern, test_data)


def analyze_pattern_usage(
    pattern_id: str,
    usage_history: List[Dict[str, Any]]
) -> EffectivenessMetrics:
    """
    Convenience function to analyze pattern usage effectiveness.
    
    Usage:
        metrics = analyze_pattern_usage(pattern_id, usage_data)
        if metrics.effectiveness_score > 0.7:
            # Pattern is performing well
    """
    validator = PatternValidator()
    return validator.calculate_pattern_effectiveness(pattern_id, usage_history)