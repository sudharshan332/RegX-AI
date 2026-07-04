"""
Pattern Learning Service for RegX-AI Agent Framework

This service manages dynamic pattern learning, user approval workflows,
and pattern effectiveness tracking for intelligent test failure triage.
"""

import json
import logging
import os
import asyncio
import time
import hashlib
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
import threading
import re

logger = logging.getLogger(__name__)


@dataclass
class PatternCandidate:
    """Represents a candidate pattern awaiting approval."""
    id: str
    regex: str
    confidence: float
    category: str
    pattern_type: str  # "intermittent" or "rdm"
    description: str
    action: str
    root_cause: str
    source_test_id: str
    source_analysis: Dict[str, Any]
    created_at: str
    status: str  # "pending", "approved", "rejected", "expired"
    user_feedback: Optional[Dict[str, Any]] = None
    approved_at: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class PatternEffectiveness:
    """Tracks effectiveness metrics for approved patterns."""
    pattern_id: str
    total_matches: int
    correct_matches: int
    false_positives: int
    last_matched: Optional[str]
    effectiveness_score: float
    created_at: str
    last_updated: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class ApprovalRequest:
    """Represents a user approval request."""
    request_id: str
    pattern_candidate: PatternCandidate
    test_context: Dict[str, Any]
    analysis_summary: Dict[str, Any]
    created_at: str
    expires_at: str
    status: str
    response_data: Optional[Dict[str, Any]] = None
    
    def is_expired(self) -> bool:
        """Check if the approval request has expired."""
        return datetime.fromisoformat(self.expires_at) < datetime.utcnow()


class PatternLearningService:
    """Service for managing pattern learning and user approval workflows."""
    
    def __init__(self):
        # File paths for different pattern types
        self.intermittent_patterns_file = "/Users/sudharshan.musali/regx/RegX-AI/backend/intermittent_patterns.json"
        self.rdm_patterns_file = "/Users/sudharshan.musali/regx/RegX-AI/data/rdm_failure_patterns.json"
        
        # Tracking files
        self.candidates_file = "/Users/sudharshan.musali/regx/RegX-AI/backend/agents/data/pattern_candidates.json"
        self.effectiveness_file = "/Users/sudharshan.musali/regx/RegX-AI/backend/agents/data/pattern_effectiveness.json"
        self.approvals_file = "/Users/sudharshan.musali/regx/RegX-AI/backend/agents/data/approval_requests.json"
        
        # Configuration
        self.approval_timeout = 1800  # 30 minutes
        self.effectiveness_threshold = 0.7  # Minimum effectiveness score to keep pattern
        self.min_matches_for_evaluation = 5  # Minimum matches before evaluating effectiveness
        
        # In-memory state
        self._pattern_candidates: Dict[str, PatternCandidate] = {}
        self._pattern_effectiveness: Dict[str, PatternEffectiveness] = {}
        self._approval_requests: Dict[str, ApprovalRequest] = {}
        self._lock = threading.Lock()
        
        # Initialize data directories and files
        self._initialize_data_files()
        self._load_state()
    
    async def suggest_pattern(
        self,
        test_result: Dict[str, Any],
        jita_analysis: Dict[str, Any],
        glean_results: Dict[str, Any],
        ai_analysis: Dict[str, Any]
    ) -> Optional[PatternCandidate]:
        """
        Create a pattern candidate based on analysis results.
        
        Args:
            test_result: Original test result data
            jita_analysis: Analysis from JITA API
            glean_results: Results from Glean search
            ai_analysis: AI analysis results
            
        Returns:
            PatternCandidate if a valid pattern can be suggested
        """
        try:
            # Extract pattern information from analysis
            pattern_info = self._extract_pattern_info(test_result, jita_analysis, ai_analysis)
            if not pattern_info:
                return None
            
            # Generate pattern candidate
            candidate = PatternCandidate(
                id=self._generate_pattern_id(pattern_info["regex"], pattern_info["category"]),
                regex=pattern_info["regex"],
                confidence=pattern_info["confidence"],
                category=pattern_info["category"],
                pattern_type=pattern_info["pattern_type"],
                description=pattern_info["description"],
                action=pattern_info["action"],
                root_cause=pattern_info["root_cause"],
                source_test_id=test_result.get("test_id", ""),
                source_analysis={
                    "jita_summary": jita_analysis.get("summary", ""),
                    "glean_findings": glean_results.get("summary", ""),
                    "ai_confidence": ai_analysis.get("confidence", 0.0),
                    "failure_stage": jita_analysis.get("failure_stage", ""),
                    "intermittency_indicators": ai_analysis.get("intermittency_score", 0.0)
                },
                created_at=datetime.utcnow().isoformat(),
                status="pending"
            )
            
            # Validate pattern before suggesting
            if not self._validate_pattern_candidate(candidate):
                return None
            
            # Check for duplicates
            if self._is_duplicate_pattern(candidate):
                logger.info(f"Pattern candidate {candidate.id} is duplicate, skipping")
                return None
            
            # Store candidate
            with self._lock:
                self._pattern_candidates[candidate.id] = candidate
                self._save_candidates()
            
            logger.info(f"Created pattern candidate: {candidate.id}")
            return candidate
            
        except Exception as e:
            logger.error(f"Error creating pattern candidate: {str(e)}")
            return None
    
    async def request_user_approval(
        self,
        pattern_candidate: PatternCandidate,
        test_context: Dict[str, Any],
        analysis_summary: Dict[str, Any]
    ) -> str:
        """
        Create a user approval request for the pattern candidate.
        
        Args:
            pattern_candidate: The pattern to request approval for
            test_context: Context about the test that generated this pattern
            analysis_summary: Summary of the analysis results
            
        Returns:
            Request ID for tracking the approval
        """
        request_id = self._generate_request_id()
        expires_at = datetime.utcnow() + timedelta(seconds=self.approval_timeout)
        
        approval_request = ApprovalRequest(
            request_id=request_id,
            pattern_candidate=pattern_candidate,
            test_context=test_context,
            analysis_summary=analysis_summary,
            created_at=datetime.utcnow().isoformat(),
            expires_at=expires_at.isoformat(),
            status="pending"
        )
        
        with self._lock:
            self._approval_requests[request_id] = approval_request
            self._save_approval_requests()
        
        logger.info(f"Created approval request: {request_id} for pattern: {pattern_candidate.id}")
        return request_id
    
    async def process_user_approval(
        self,
        request_id: str,
        user_response: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Process user response to pattern approval request.
        
        Args:
            request_id: The approval request ID
            user_response: User's response data
            
        Returns:
            Processing result with actions to take
        """
        with self._lock:
            if request_id not in self._approval_requests:
                return {
                    "success": False,
                    "error": "Approval request not found",
                    "request_id": request_id
                }
            
            approval_request = self._approval_requests[request_id]
            
            # Check if expired
            if approval_request.is_expired():
                approval_request.status = "expired"
                self._save_approval_requests()
                return {
                    "success": False,
                    "error": "Approval request expired",
                    "request_id": request_id
                }
            
            # Process the response
            action = user_response.get("action", "").lower()
            approval_request.response_data = user_response
            
            if action == "approve":
                return await self._handle_approval(approval_request)
            elif action == "reject":
                return await self._handle_rejection(approval_request, user_response)
            elif action == "modify":
                return await self._handle_modification(approval_request, user_response)
            else:
                return {
                    "success": False,
                    "error": f"Unknown action: {action}",
                    "request_id": request_id
                }
    
    async def add_approved_pattern(
        self,
        pattern_candidate: PatternCandidate,
        user_modifications: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Add an approved pattern to the appropriate pattern file.
        
        Args:
            pattern_candidate: The approved pattern candidate
            user_modifications: Optional modifications from user
            
        Returns:
            True if pattern was added successfully
        """
        try:
            # Apply user modifications if provided
            if user_modifications:
                pattern_candidate = self._apply_modifications(pattern_candidate, user_modifications)
            
            # Determine target file and format
            target_file = (self.intermittent_patterns_file 
                          if pattern_candidate.pattern_type == "intermittent" 
                          else self.rdm_patterns_file)
            
            pattern_data = self._format_pattern_for_file(pattern_candidate)
            
            # Add to pattern file
            success = await self._add_to_pattern_file(target_file, pattern_data)
            
            if success:
                # Update candidate status
                pattern_candidate.status = "approved"
                pattern_candidate.approved_at = datetime.utcnow().isoformat()
                
                # Initialize effectiveness tracking
                effectiveness = PatternEffectiveness(
                    pattern_id=pattern_candidate.id,
                    total_matches=0,
                    correct_matches=0,
                    false_positives=0,
                    last_matched=None,
                    effectiveness_score=1.0,  # Start optimistic
                    created_at=datetime.utcnow().isoformat(),
                    last_updated=datetime.utcnow().isoformat()
                )
                
                with self._lock:
                    self._pattern_candidates[pattern_candidate.id] = pattern_candidate
                    self._pattern_effectiveness[pattern_candidate.id] = effectiveness
                    self._save_candidates()
                    self._save_effectiveness()
                
                logger.info(f"Successfully added pattern: {pattern_candidate.id}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error adding approved pattern {pattern_candidate.id}: {str(e)}")
            return False
    
    async def track_pattern_usage(
        self,
        pattern_id: str,
        matched: bool,
        correct: Optional[bool] = None
    ) -> None:
        """
        Track usage of a pattern for effectiveness evaluation.
        
        Args:
            pattern_id: ID of the pattern that was used
            matched: Whether the pattern matched
            correct: Whether the match was correct (if known)
        """
        try:
            with self._lock:
                if pattern_id not in self._pattern_effectiveness:
                    # Initialize if not exists (for existing patterns)
                    self._pattern_effectiveness[pattern_id] = PatternEffectiveness(
                        pattern_id=pattern_id,
                        total_matches=0,
                        correct_matches=0,
                        false_positives=0,
                        last_matched=None,
                        effectiveness_score=1.0,
                        created_at=datetime.utcnow().isoformat(),
                        last_updated=datetime.utcnow().isoformat()
                    )
                
                effectiveness = self._pattern_effectiveness[pattern_id]
                
                if matched:
                    effectiveness.total_matches += 1
                    effectiveness.last_matched = datetime.utcnow().isoformat()
                    
                    if correct is True:
                        effectiveness.correct_matches += 1
                    elif correct is False:
                        effectiveness.false_positives += 1
                
                # Update effectiveness score
                effectiveness.effectiveness_score = self._calculate_effectiveness_score(effectiveness)
                effectiveness.last_updated = datetime.utcnow().isoformat()
                
                self._save_effectiveness()
            
        except Exception as e:
            logger.error(f"Error tracking pattern usage for {pattern_id}: {str(e)}")
    
    def get_pattern_effectiveness_report(self) -> Dict[str, Any]:
        """Get effectiveness report for all tracked patterns."""
        with self._lock:
            report = {
                "total_patterns": len(self._pattern_effectiveness),
                "patterns": [],
                "summary": {
                    "high_effectiveness": 0,
                    "medium_effectiveness": 0,
                    "low_effectiveness": 0,
                    "needs_review": 0
                }
            }
            
            for effectiveness in self._pattern_effectiveness.values():
                pattern_info = {
                    "pattern_id": effectiveness.pattern_id,
                    "total_matches": effectiveness.total_matches,
                    "correct_matches": effectiveness.correct_matches,
                    "false_positives": effectiveness.false_positives,
                    "effectiveness_score": effectiveness.effectiveness_score,
                    "last_matched": effectiveness.last_matched,
                    "created_at": effectiveness.created_at
                }
                
                report["patterns"].append(pattern_info)
                
                # Categorize effectiveness
                if effectiveness.effectiveness_score >= 0.8:
                    report["summary"]["high_effectiveness"] += 1
                elif effectiveness.effectiveness_score >= 0.6:
                    report["summary"]["medium_effectiveness"] += 1
                elif effectiveness.effectiveness_score >= 0.3:
                    report["summary"]["low_effectiveness"] += 1
                else:
                    report["summary"]["needs_review"] += 1
            
            return report
    
    def _extract_pattern_info(
        self,
        test_result: Dict[str, Any],
        jita_analysis: Dict[str, Any],
        ai_analysis: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Extract pattern information from analysis results."""
        # Get error signature from various sources
        error_sources = [
            ai_analysis.get("error_signature", ""),
            test_result.get("error_message", ""),
            jita_analysis.get("primary_exception", {}).get("message", "")
        ]
        
        error_signature = None
        for source in error_sources:
            if source and len(source.strip()) > 10:
                error_signature = source.strip()
                break
        
        if not error_signature:
            return None
        
        # Generate regex pattern
        regex_pattern = self._generate_regex_from_signature(error_signature)
        if not regex_pattern:
            return None
        
        # Determine pattern type and category
        pattern_type, category = self._determine_pattern_type(test_result, jita_analysis)
        
        # Calculate confidence
        confidence = self._calculate_pattern_confidence(ai_analysis, jita_analysis)
        
        # Generate descriptions
        description = self._generate_pattern_description(error_signature, category, jita_analysis)
        action = self._generate_pattern_action(category)
        root_cause = self._generate_pattern_root_cause(jita_analysis, ai_analysis)
        
        return {
            "regex": regex_pattern,
            "confidence": confidence,
            "category": category,
            "pattern_type": pattern_type,
            "description": description,
            "action": action,
            "root_cause": root_cause
        }
    
    def _generate_regex_from_signature(self, error_signature: str) -> Optional[str]:
        """Generate regex pattern from error signature."""
        try:
            # Clean the signature
            cleaned = self._clean_error_signature(error_signature)
            
            # Escape special regex characters
            escaped = re.escape(cleaned)
            
            # Replace placeholders with regex patterns
            pattern = escaped.replace(r'\[TIMESTAMP\]', r'\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}')
            pattern = pattern.replace(r'\[UUID\]', r'[0-9a-fA-F-]{36}')
            pattern = pattern.replace(r'\[IP\]', r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}')
            pattern = pattern.replace(r'\[NUMBER\]', r'\d+')
            pattern = pattern.replace(r'\ ', r'\s+')  # Flexible whitespace
            
            # Test the pattern
            re.compile(pattern)
            return pattern
            
        except re.error as e:
            logger.error(f"Failed to generate regex pattern: {e}")
            return None
    
    def _clean_error_signature(self, signature: str) -> str:
        """Clean error signature for pattern generation."""
        # Replace variable content with placeholders
        cleaned = re.sub(r'\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}[\.\d]*Z?', '[TIMESTAMP]', signature)
        cleaned = re.sub(r'\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b', '[UUID]', cleaned)
        cleaned = re.sub(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '[IP]', cleaned)
        cleaned = re.sub(r'\b\d+\b', '[NUMBER]', cleaned)
        
        # Normalize whitespace
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        
        return cleaned
    
    def _determine_pattern_type(
        self,
        test_result: Dict[str, Any],
        jita_analysis: Dict[str, Any]
    ) -> Tuple[str, str]:
        """Determine pattern type and category."""
        status = test_result.get("status", "").lower()
        error_message = test_result.get("error_message", "").lower()
        failure_stage = jita_analysis.get("failure_stage", "").lower()
        
        # RDM patterns for skipped tests or infrastructure issues
        rdm_indicators = ["rdm", "base cluster", "nested vm", "resource allocation", "foundation"]
        if status == "skipped" or any(indicator in error_message for indicator in rdm_indicators):
            return "rdm", "INFRA_INTERMITTENT"
        
        # Intermittent patterns for setup stage failures
        if failure_stage in ["setup", "initialization"]:
            return "intermittent", "INTERMITTENT"
        
        # Default to intermittent for failed tests
        return "intermittent", "INTERMITTENT"
    
    def _calculate_pattern_confidence(
        self,
        ai_analysis: Dict[str, Any],
        jita_analysis: Dict[str, Any]
    ) -> float:
        """Calculate confidence score for the pattern."""
        base_confidence = ai_analysis.get("confidence", 0.5)
        
        # Boost confidence based on data quality
        if jita_analysis.get("success", False):
            base_confidence += 0.1
        
        if jita_analysis.get("primary_exception"):
            base_confidence += 0.1
        
        if jita_analysis.get("failure_stage"):
            base_confidence += 0.05
        
        # Cap at 95%
        return min(base_confidence, 0.95)
    
    def _generate_pattern_description(
        self,
        error_signature: str,
        category: str,
        jita_analysis: Dict[str, Any]
    ) -> str:
        """Generate human-readable pattern description."""
        failure_stage = jita_analysis.get("failure_stage", "execution")
        
        if "timeout" in error_signature.lower():
            return f"Timeout during {failure_stage} - known intermittent issue"
        elif "connection" in error_signature.lower():
            return f"Connection failure during {failure_stage} - intermittent networking issue"
        elif "cluster" in error_signature.lower():
            return f"Cluster operation failure during {failure_stage} - intermittent resource issue"
        else:
            return f"Intermittent failure pattern during {failure_stage}"
    
    def _generate_pattern_action(self, category: str) -> str:
        """Generate action recommendation for the pattern."""
        action_map = {
            "INTERMITTENT": "Retry deployment, issue typically resolves on subsequent attempts",
            "INFRA_INTERMITTENT": "Check infrastructure status and retry deployment",
            "INFRA_RESOURCE": "Verify resource availability and retry or escalate to infrastructure team",
            "INFRA_NODE": "Check node health and potentially exclude from deployment"
        }
        
        return action_map.get(category, "Investigate and retry deployment after addressing underlying cause")
    
    def _generate_pattern_root_cause(
        self,
        jita_analysis: Dict[str, Any],
        ai_analysis: Dict[str, Any]
    ) -> str:
        """Generate root cause analysis."""
        causes = []
        
        # From JITA analysis
        if jita_analysis.get("failure_stage"):
            causes.append(f"Failure during {jita_analysis['failure_stage']} stage")
        
        # From AI analysis
        intermittency_score = ai_analysis.get("intermittency_score", 0)
        if intermittency_score > 0.7:
            causes.append("High intermittency indicators suggest non-deterministic failure")
        
        # Generic causes based on error patterns
        error_signature = ai_analysis.get("error_signature", "").lower()
        if "timeout" in error_signature:
            causes.append("Timeout-based failure indicating resource or network delays")
        elif "connection" in error_signature:
            causes.append("Network connectivity issues")
        
        if not causes:
            causes.append("Intermittent failure with no clear deterministic root cause")
        
        return ". ".join(causes)
    
    def _validate_pattern_candidate(self, candidate: PatternCandidate) -> bool:
        """Validate that pattern candidate is properly formed."""
        try:
            # Test regex compilation
            re.compile(candidate.regex)
            
            # Check required fields
            required_fields = ["id", "regex", "confidence", "category", "description"]
            for field in required_fields:
                if not getattr(candidate, field):
                    logger.error(f"Pattern candidate missing required field: {field}")
                    return False
            
            # Validate confidence range
            if not 0.0 <= candidate.confidence <= 1.0:
                logger.error(f"Invalid confidence score: {candidate.confidence}")
                return False
            
            # Check regex length (prevent overly complex patterns)
            if len(candidate.regex) > 500:
                logger.error(f"Regex pattern too long: {len(candidate.regex)}")
                return False
            
            return True
            
        except re.error as e:
            logger.error(f"Invalid regex in pattern candidate: {e}")
            return False
        except Exception as e:
            logger.error(f"Pattern validation error: {e}")
            return False
    
    def _is_duplicate_pattern(self, candidate: PatternCandidate) -> bool:
        """Check if pattern candidate is duplicate of existing patterns."""
        # Check against existing candidates
        for existing in self._pattern_candidates.values():
            if existing.regex == candidate.regex:
                return True
        
        # Check against existing patterns in files (basic check)
        # This could be enhanced to do more sophisticated similarity checking
        return False
    
    def _generate_pattern_id(self, regex_pattern: str, category: str) -> str:
        """Generate unique pattern ID."""
        content = f"{regex_pattern}_{category}_{int(time.time())}"
        hash_obj = hashlib.md5(content.encode())
        hash_hex = hash_obj.hexdigest()[:8]
        
        category_prefix = category.lower().replace("_", "")[:4]
        return f"ai_{category_prefix}_{hash_hex}"
    
    def _generate_request_id(self) -> str:
        """Generate unique request ID."""
        import uuid
        return f"approval_{uuid.uuid4().hex[:8]}_{int(time.time())}"
    
    async def _handle_approval(self, approval_request: ApprovalRequest) -> Dict[str, Any]:
        """Handle user approval of pattern."""
        approval_request.status = "approved"
        self._save_approval_requests()
        
        # Add the pattern
        success = await self.add_approved_pattern(approval_request.pattern_candidate)
        
        return {
            "success": success,
            "action": "pattern_added" if success else "add_failed",
            "pattern_id": approval_request.pattern_candidate.id,
            "request_id": approval_request.request_id
        }
    
    async def _handle_rejection(
        self,
        approval_request: ApprovalRequest,
        user_response: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle user rejection of pattern."""
        approval_request.status = "rejected"
        approval_request.pattern_candidate.status = "rejected"
        approval_request.pattern_candidate.user_feedback = user_response.get("feedback", {})
        
        self._save_approval_requests()
        self._save_candidates()
        
        return {
            "success": True,
            "action": "pattern_rejected",
            "reason": user_response.get("reason", "User rejected"),
            "request_id": approval_request.request_id
        }
    
    async def _handle_modification(
        self,
        approval_request: ApprovalRequest,
        user_response: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle user modification of pattern."""
        modifications = user_response.get("modifications", {})
        if not modifications:
            return {
                "success": False,
                "error": "No modifications provided",
                "request_id": approval_request.request_id
            }
        
        approval_request.status = "approved"
        self._save_approval_requests()
        
        # Add the modified pattern
        success = await self.add_approved_pattern(
            approval_request.pattern_candidate,
            modifications
        )
        
        return {
            "success": success,
            "action": "modified_pattern_added" if success else "add_failed",
            "pattern_id": approval_request.pattern_candidate.id,
            "request_id": approval_request.request_id,
            "modifications": modifications
        }
    
    def _apply_modifications(
        self,
        pattern_candidate: PatternCandidate,
        modifications: Dict[str, Any]
    ) -> PatternCandidate:
        """Apply user modifications to pattern candidate."""
        # Create a copy and apply modifications
        modified = PatternCandidate(**asdict(pattern_candidate))
        
        for field, value in modifications.items():
            if hasattr(modified, field) and value is not None:
                setattr(modified, field, value)
        
        return modified
    
    def _format_pattern_for_file(self, pattern_candidate: PatternCandidate) -> Dict[str, Any]:
        """Format pattern candidate for addition to pattern file."""
        return {
            "id": pattern_candidate.id,
            "regex": pattern_candidate.regex,
            "confidence": pattern_candidate.confidence,
            "category": pattern_candidate.category,
            "description": pattern_candidate.description,
            "action": pattern_candidate.action,
            "root_cause": pattern_candidate.root_cause,
            "auto_triage": True,
            "created_by": "ai_learning",
            "created_at": pattern_candidate.created_at,
            "source_test": pattern_candidate.source_test_id
        }
    
    async def _add_to_pattern_file(self, file_path: str, pattern_data: Dict[str, Any]) -> bool:
        """Add pattern to the appropriate pattern file."""
        try:
            # Read existing patterns
            if os.path.exists(file_path):
                with open(file_path, 'r') as f:
                    data = json.load(f)
            else:
                data = {}
            
            # Determine the pattern array key
            if "intermittent" in file_path:
                key = "intermittent_patterns"
            else:
                key = "failure_patterns" if "failure_patterns" in data else "patterns"
            
            # Ensure pattern array exists
            if key not in data:
                data[key] = []
            
            # Add the new pattern
            data[key].append(pattern_data)
            
            # Write back to file
            with open(file_path, 'w') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Added pattern {pattern_data['id']} to {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error adding pattern to file {file_path}: {str(e)}")
            return False
    
    def _calculate_effectiveness_score(self, effectiveness: PatternEffectiveness) -> float:
        """Calculate effectiveness score for a pattern."""
        if effectiveness.total_matches == 0:
            return 1.0  # No data yet, assume good
        
        if effectiveness.total_matches < self.min_matches_for_evaluation:
            # Not enough data, maintain current score
            return effectiveness.effectiveness_score
        
        # Calculate based on correct vs false positive ratio
        if effectiveness.correct_matches + effectiveness.false_positives == 0:
            return 1.0  # No feedback yet
        
        total_feedback = effectiveness.correct_matches + effectiveness.false_positives
        accuracy = effectiveness.correct_matches / total_feedback
        
        # Weight by coverage (more matches = more confidence in score)
        coverage_weight = min(effectiveness.total_matches / (self.min_matches_for_evaluation * 2), 1.0)
        
        return accuracy * coverage_weight + (1 - coverage_weight) * effectiveness.effectiveness_score
    
    def _initialize_data_files(self):
        """Initialize data directories and files."""
        data_dir = os.path.dirname(self.candidates_file)
        os.makedirs(data_dir, exist_ok=True)
        
        # Initialize files if they don't exist
        for file_path in [self.candidates_file, self.effectiveness_file, self.approvals_file]:
            if not os.path.exists(file_path):
                with open(file_path, 'w') as f:
                    json.dump({}, f)
    
    def _load_state(self):
        """Load state from persistent files."""
        try:
            # Load pattern candidates
            if os.path.exists(self.candidates_file):
                with open(self.candidates_file, 'r') as f:
                    data = json.load(f)
                    for candidate_id, candidate_data in data.items():
                        self._pattern_candidates[candidate_id] = PatternCandidate(**candidate_data)
            
            # Load effectiveness data
            if os.path.exists(self.effectiveness_file):
                with open(self.effectiveness_file, 'r') as f:
                    data = json.load(f)
                    for pattern_id, effectiveness_data in data.items():
                        self._pattern_effectiveness[pattern_id] = PatternEffectiveness(**effectiveness_data)
            
            # Load approval requests
            if os.path.exists(self.approvals_file):
                with open(self.approvals_file, 'r') as f:
                    data = json.load(f)
                    for request_id, request_data in data.items():
                        candidate_data = request_data.pop("pattern_candidate")
                        request_data["pattern_candidate"] = PatternCandidate(**candidate_data)
                        self._approval_requests[request_id] = ApprovalRequest(**request_data)
            
        except Exception as e:
            logger.error(f"Error loading pattern learning state: {str(e)}")
    
    def _save_candidates(self):
        """Save pattern candidates to file."""
        try:
            data = {cid: candidate.to_dict() for cid, candidate in self._pattern_candidates.items()}
            with open(self.candidates_file, 'w') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error saving pattern candidates: {str(e)}")
    
    def _save_effectiveness(self):
        """Save effectiveness data to file."""
        try:
            data = {pid: eff.to_dict() for pid, eff in self._pattern_effectiveness.items()}
            with open(self.effectiveness_file, 'w') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error saving pattern effectiveness: {str(e)}")
    
    def _save_approval_requests(self):
        """Save approval requests to file."""
        try:
            data = {}
            for request_id, request in self._approval_requests.items():
                request_dict = asdict(request)
                request_dict["pattern_candidate"] = request.pattern_candidate.to_dict()
                data[request_id] = request_dict
            
            with open(self.approvals_file, 'w') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error saving approval requests: {str(e)}")


# Utility functions for agent integration

async def create_pattern_from_analysis(
    test_result: Dict[str, Any],
    jita_analysis: Dict[str, Any],
    glean_results: Dict[str, Any],
    ai_analysis: Dict[str, Any]
) -> Optional[PatternCandidate]:
    """
    Convenience function to create pattern candidate from analysis.
    
    Usage:
        pattern = await create_pattern_from_analysis(
            test_result, jita_analysis, glean_results, ai_analysis
        )
        if pattern:
            # Request user approval
    """
    service = PatternLearningService()
    return await service.suggest_pattern(test_result, jita_analysis, glean_results, ai_analysis)


async def handle_pattern_approval_flow(
    pattern_candidate: PatternCandidate,
    test_context: Dict[str, Any],
    analysis_summary: Dict[str, Any]
) -> str:
    """
    Convenience function to start approval flow.
    
    Usage:
        request_id = await handle_pattern_approval_flow(
            pattern_candidate, test_context, analysis_summary
        )
        # Present approval interface to user
    """
    service = PatternLearningService()
    return await service.request_user_approval(pattern_candidate, test_context, analysis_summary)


def track_pattern_match(pattern_id: str, correct: bool):
    """
    Convenience function to track pattern effectiveness.
    
    Usage:
        # When pattern is used and result is known
        track_pattern_match(pattern_id, was_correct_match)
    """
    service = PatternLearningService()
    asyncio.create_task(service.track_pattern_usage(pattern_id, True, correct))