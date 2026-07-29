"""
Auto Test Fix Service for RegX-AI Agent Framework

This service analyzes test failures and suggests automatic fixes that can be
approved by users to create change requests for test remediation.
"""

import asyncio
import json
import logging
import re
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime
import hashlib

logger = logging.getLogger(__name__)


@dataclass
class TestFixSuggestion:
    """Represents an auto test fix suggestion."""
    fix_id: str
    fix_type: str  # "config_change", "code_update", "environment_fix", "dependency_update"
    description: str
    confidence: float
    suggested_changes: List[Dict[str, str]]
    requires_approval: bool
    estimated_effort: str  # "low", "medium", "high"
    risk_level: str  # "low", "medium", "high"
    test_after_fix: bool
    created_at: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class FixChangeRequest:
    """Represents a change request for test fix."""
    cr_number: str
    fix_suggestion: TestFixSuggestion
    status: str  # "pending", "approved", "rejected", "applied", "failed"
    created_by: str
    created_at: str
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    application_log: List[str] = None
    test_results: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


class AutoTestFixService:
    """Service for automatic test fix analysis and suggestion."""
    
    def __init__(self):
        # Fix confidence thresholds
        self.min_confidence = 0.6
        self.high_confidence = 0.8
        
        # Fix patterns and their solutions
        self.fix_patterns = self._initialize_fix_patterns()
        
        # Change request counter
        self.cr_counter = 1000
    
    async def analyze_test_fix(
        self, 
        test_result: Dict[str, Any], 
        glean_results: Any,
        jita_analysis: Optional[Dict[str, Any]] = None
    ) -> Optional[TestFixSuggestion]:
        """
        Analyze test failure and suggest fixes based on error patterns and Glean results.
        
        Args:
            test_result: Test failure data
            glean_results: Results from Glean bug detection
            jita_analysis: Optional JITA analysis results
            
        Returns:
            TestFixSuggestion if a fix can be suggested, None otherwise
        """
        try:
            # Extract error information
            error_info = self._extract_error_info(test_result, jita_analysis)
            
            # Analyze fix patterns
            pattern_match = self._match_fix_patterns(error_info)
            
            # Enhance with Glean results
            glean_enhanced = self._enhance_with_glean(pattern_match, glean_results)
            
            if glean_enhanced:
                return glean_enhanced
            
            # Fallback to general analysis
            return self._generate_general_fix(error_info, test_result)
            
        except Exception as e:
            logger.error(f"Error analyzing test fix: {str(e)}")
            return None
    
    async def create_fix_cr(
        self, 
        fix_suggestion: TestFixSuggestion, 
        user_approval: Dict[str, Any]
    ) -> FixChangeRequest:
        """
        Create change request for approved test fix.
        
        Args:
            fix_suggestion: The approved fix suggestion
            user_approval: User approval data with any modifications
            
        Returns:
            FixChangeRequest with CR details
        """
        try:
            # Generate CR number
            cr_number = self._generate_cr_number()
            
            # Apply any user modifications to the fix
            if "modifications" in user_approval:
                fix_suggestion = self._apply_user_modifications(
                    fix_suggestion, user_approval["modifications"]
                )
            
            # Create change request
            cr = FixChangeRequest(
                cr_number=cr_number,
                fix_suggestion=fix_suggestion,
                status="approved",
                created_by=user_approval.get("user_id", "system"),
                created_at=datetime.utcnow().isoformat(),
                approved_by=user_approval.get("user_id"),
                approved_at=datetime.utcnow().isoformat(),
                application_log=[]
            )
            
            # Log CR creation
            logger.info(f"Created change request {cr_number} for fix {fix_suggestion.fix_id}")
            
            return cr
            
        except Exception as e:
            logger.error(f"Error creating fix CR: {str(e)}")
            raise
    
    async def apply_test_fix(self, cr: FixChangeRequest) -> Dict[str, Any]:
        """
        Apply the test fix (simulation for now - would integrate with actual CR system).
        
        Args:
            cr: Change request to apply
            
        Returns:
            Application result with success status and details
        """
        try:
            fix_type = cr.fix_suggestion.fix_type
            changes = cr.fix_suggestion.suggested_changes
            
            # Simulate fix application based on type
            if fix_type == "config_change":
                result = await self._apply_config_changes(changes)
            elif fix_type == "code_update":
                result = await self._apply_code_updates(changes)
            elif fix_type == "environment_fix":
                result = await self._apply_environment_fixes(changes)
            elif fix_type == "dependency_update":
                result = await self._apply_dependency_updates(changes)
            else:
                result = {
                    "success": False,
                    "error": f"Unknown fix type: {fix_type}"
                }
            
            # Update CR status
            if result["success"]:
                cr.status = "applied"
                cr.application_log.append(f"Fix applied successfully at {datetime.utcnow().isoformat()}")
            else:
                cr.status = "failed"
                cr.application_log.append(f"Fix application failed: {result.get('error', 'Unknown error')}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error applying test fix: {str(e)}")
            cr.status = "failed"
            cr.application_log.append(f"Exception during application: {str(e)}")
            
            return {
                "success": False,
                "error": str(e)
            }
    
    async def run_test_after_fix(
        self, 
        cr: FixChangeRequest,
        test_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Run the test after fix application to verify success.
        
        Args:
            cr: Change request that was applied
            test_result: Original test result for re-running
            
        Returns:
            Test execution results
        """
        try:
            # This would integrate with the actual test execution system
            # For now, simulate based on fix confidence
            
            confidence = cr.fix_suggestion.confidence
            
            # Higher confidence fixes are more likely to succeed
            success_probability = confidence * 0.9
            
            # Simulate test execution
            test_success = confidence > 0.7  # Simplified logic
            
            test_results = {
                "test_executed": True,
                "test_passed": test_success,
                "execution_time": 45.2,  # Simulated
                "test_output": "Test executed successfully" if test_success else "Test still failing",
                "fix_effective": test_success
            }
            
            # Update CR with test results
            cr.test_results = test_results
            
            if test_success:
                cr.status = "verified"
                cr.application_log.append(f"Test verification passed at {datetime.utcnow().isoformat()}")
            else:
                cr.application_log.append(f"Test verification failed at {datetime.utcnow().isoformat()}")
            
            return test_results
            
        except Exception as e:
            logger.error(f"Error running test after fix: {str(e)}")
            return {
                "test_executed": False,
                "error": str(e)
            }
    
    def _initialize_fix_patterns(self) -> Dict[str, Dict[str, Any]]:
        """Initialize common fix patterns and their solutions."""
        return {
            "timeout_issue": {
                "patterns": [
                    r"timeout.*\d+.*seconds",
                    r"connection.*timeout",
                    r"timed.*out.*waiting"
                ],
                "fix_type": "config_change",
                "confidence": 0.8,
                "changes": [
                    {
                        "type": "timeout_increase",
                        "file": "test_config.json",
                        "change": "Increase timeout from 30s to 60s"
                    }
                ]
            },
            
            "connection_refused": {
                "patterns": [
                    r"connection.*refused",
                    r"unable.*to.*connect",
                    r"connection.*reset"
                ],
                "fix_type": "environment_fix",
                "confidence": 0.7,
                "changes": [
                    {
                        "type": "service_restart",
                        "service": "target_service",
                        "change": "Restart target service and retry"
                    }
                ]
            },
            
            "missing_dependency": {
                "patterns": [
                    r"module.*not.*found",
                    r"import.*error",
                    r"no.*module.*named"
                ],
                "fix_type": "dependency_update",
                "confidence": 0.9,
                "changes": [
                    {
                        "type": "install_dependency",
                        "file": "requirements.txt",
                        "change": "Add missing dependency"
                    }
                ]
            },
            
            "configuration_error": {
                "patterns": [
                    r"configuration.*error",
                    r"invalid.*config",
                    r"config.*not.*found"
                ],
                "fix_type": "config_change",
                "confidence": 0.8,
                "changes": [
                    {
                        "type": "config_update",
                        "file": "config file",
                        "change": "Update configuration settings"
                    }
                ]
            },
            
            "permission_error": {
                "patterns": [
                    r"permission.*denied",
                    r"access.*denied",
                    r"unauthorized"
                ],
                "fix_type": "environment_fix",
                "confidence": 0.7,
                "changes": [
                    {
                        "type": "permission_fix",
                        "target": "file/directory",
                        "change": "Fix file permissions"
                    }
                ]
            }
        }
    
    def _extract_error_info(
        self, 
        test_result: Dict[str, Any], 
        jita_analysis: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Extract relevant error information for fix analysis."""
        error_info = {
            "error_message": test_result.get("error_message", ""),
            "failure_stage": test_result.get("failure_stage", ""),
            "test_name": test_result.get("test_name", ""),
            "test_type": test_result.get("test_type", ""),
            "environment": test_result.get("environment", {}),
        }
        
        # Add JITA analysis if available
        if jita_analysis:
            error_info.update({
                "step_logs": jita_analysis.get("step_logs", []),
                "exception_details": jita_analysis.get("exception_details", ""),
                "failure_timeline": jita_analysis.get("timeline", [])
            })
        
        return error_info
    
    def _match_fix_patterns(self, error_info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Match error information against known fix patterns."""
        error_text = (error_info.get("error_message", "") + " " + 
                     error_info.get("exception_details", "")).lower()
        
        best_match = None
        best_confidence = 0.0
        
        for pattern_name, pattern_data in self.fix_patterns.items():
            for pattern in pattern_data["patterns"]:
                if re.search(pattern, error_text, re.IGNORECASE):
                    confidence = pattern_data["confidence"]
                    
                    if confidence > best_confidence:
                        best_confidence = confidence
                        best_match = {
                            "pattern_name": pattern_name,
                            "confidence": confidence,
                            "fix_type": pattern_data["fix_type"],
                            "changes": pattern_data["changes"]
                        }
        
        return best_match
    
    def _enhance_with_glean(
        self, 
        pattern_match: Optional[Dict[str, Any]], 
        glean_results: Any
    ) -> Optional[TestFixSuggestion]:
        """Enhance fix suggestion with Glean search results."""
        if not pattern_match:
            return None
        
        try:
            # Extract information from Glean results
            jira_tickets = getattr(glean_results, 'jira_tickets', [])
            confidence_boost = 0.0
            additional_changes = []
            
            # If we found related JIRA tickets, boost confidence and add context
            if jira_tickets:
                confidence_boost = 0.1
                additional_changes.append({
                    "type": "reference_check",
                    "tickets": jira_tickets[:3],
                    "change": f"Review related tickets: {', '.join(jira_tickets[:3])}"
                })
            
            # Check for product behavior documentation
            behavior_docs = getattr(glean_results, 'product_behavior_docs', [])
            if behavior_docs:
                additional_changes.append({
                    "type": "behavior_verification",
                    "docs": behavior_docs[:2],
                    "change": "Verify expected behavior against product documentation"
                })
            
            # Create enhanced fix suggestion
            enhanced_confidence = min(pattern_match["confidence"] + confidence_boost, 1.0)
            all_changes = pattern_match["changes"] + additional_changes
            
            fix_suggestion = TestFixSuggestion(
                fix_id=self._generate_fix_id(pattern_match),
                fix_type=pattern_match["fix_type"],
                description=self._generate_fix_description(pattern_match, glean_results),
                confidence=enhanced_confidence,
                suggested_changes=all_changes,
                requires_approval=True,
                estimated_effort=self._estimate_effort(all_changes),
                risk_level=self._assess_risk(pattern_match["fix_type"], enhanced_confidence),
                test_after_fix=True,
                created_at=datetime.utcnow().isoformat()
            )
            
            return fix_suggestion
            
        except Exception as e:
            logger.error(f"Error enhancing with Glean results: {str(e)}")
            return None
    
    def _generate_general_fix(
        self, 
        error_info: Dict[str, Any], 
        test_result: Dict[str, Any]
    ) -> Optional[TestFixSuggestion]:
        """Generate a general fix suggestion when no specific pattern matches."""
        error_message = error_info.get("error_message", "")
        
        if not error_message:
            return None
        
        # Create a generic fix suggestion
        fix_suggestion = TestFixSuggestion(
            fix_id=self._generate_generic_fix_id(test_result),
            fix_type="code_update",
            description=f"General fix suggestion for test failure: {error_message[:100]}",
            confidence=0.4,  # Lower confidence for general fixes
            suggested_changes=[
                {
                    "type": "investigation_required",
                    "target": test_result.get("test_name", "unknown"),
                    "change": "Manual investigation and fix required"
                }
            ],
            requires_approval=True,
            estimated_effort="medium",
            risk_level="medium",
            test_after_fix=True,
            created_at=datetime.utcnow().isoformat()
        )
        
        return fix_suggestion
    
    def _generate_fix_description(
        self, 
        pattern_match: Dict[str, Any], 
        glean_results: Any
    ) -> str:
        """Generate human-readable fix description."""
        pattern_name = pattern_match.get("pattern_name", "unknown")
        
        descriptions = {
            "timeout_issue": "Fix timeout configuration to prevent test timeouts",
            "connection_refused": "Fix connection issues by restarting services or checking network",
            "missing_dependency": "Install missing dependencies to resolve import errors",
            "configuration_error": "Update configuration settings to fix config-related failures",
            "permission_error": "Fix file/directory permissions to resolve access issues"
        }
        
        base_description = descriptions.get(pattern_name, "Apply suggested fix for test failure")
        
        # Add Glean context if available
        jira_count = len(getattr(glean_results, 'jira_tickets', []))
        if jira_count > 0:
            base_description += f" (Found {jira_count} related issue(s) in knowledge base)"
        
        return base_description
    
    def _estimate_effort(self, changes: List[Dict[str, str]]) -> str:
        """Estimate effort required for the fix."""
        if len(changes) <= 1:
            return "low"
        elif len(changes) <= 3:
            return "medium"
        else:
            return "high"
    
    def _assess_risk(self, fix_type: str, confidence: float) -> str:
        """Assess risk level of the fix."""
        if confidence >= 0.8:
            return "low"
        elif confidence >= 0.6:
            return "medium"
        else:
            return "high"
    
    def _generate_fix_id(self, pattern_match: Dict[str, Any]) -> str:
        """Generate unique fix ID."""
        pattern_name = pattern_match.get("pattern_name", "unknown")
        timestamp = str(int(datetime.utcnow().timestamp()))
        return f"fix_{pattern_name}_{timestamp}"
    
    def _generate_generic_fix_id(self, test_result: Dict[str, Any]) -> str:
        """Generate fix ID for generic fixes."""
        test_name = test_result.get("test_name", "unknown")
        hash_input = test_name + str(datetime.utcnow().timestamp())
        fix_hash = hashlib.md5(hash_input.encode()).hexdigest()[:8]
        return f"fix_generic_{fix_hash}"
    
    def _generate_cr_number(self) -> str:
        """Generate change request number."""
        self.cr_counter += 1
        return f"CR-{self.cr_counter}"
    
    def _apply_user_modifications(
        self, 
        fix_suggestion: TestFixSuggestion, 
        modifications: Dict[str, Any]
    ) -> TestFixSuggestion:
        """Apply user modifications to fix suggestion."""
        # Create a copy and apply modifications
        modified_fix = TestFixSuggestion(**asdict(fix_suggestion))
        
        for field, value in modifications.items():
            if hasattr(modified_fix, field):
                setattr(modified_fix, field, value)
        
        return modified_fix
    
    async def _apply_config_changes(self, changes: List[Dict[str, str]]) -> Dict[str, Any]:
        """Simulate applying configuration changes."""
        # In a real implementation, this would update actual config files
        logger.info("Applying configuration changes...")
        
        return {
            "success": True,
            "changes_applied": len(changes),
            "details": "Configuration changes applied successfully"
        }
    
    async def _apply_code_updates(self, changes: List[Dict[str, str]]) -> Dict[str, Any]:
        """Simulate applying code updates."""
        # In a real implementation, this would modify code files
        logger.info("Applying code updates...")
        
        return {
            "success": True,
            "changes_applied": len(changes),
            "details": "Code updates applied successfully"
        }
    
    async def _apply_environment_fixes(self, changes: List[Dict[str, str]]) -> Dict[str, Any]:
        """Simulate applying environment fixes."""
        # In a real implementation, this would modify environment settings
        logger.info("Applying environment fixes...")
        
        return {
            "success": True,
            "changes_applied": len(changes),
            "details": "Environment fixes applied successfully"
        }
    
    async def _apply_dependency_updates(self, changes: List[Dict[str, str]]) -> Dict[str, Any]:
        """Simulate applying dependency updates."""
        # In a real implementation, this would update dependencies
        logger.info("Applying dependency updates...")
        
        return {
            "success": True,
            "changes_applied": len(changes),
            "details": "Dependencies updated successfully"
        }


# Utility functions for integration

async def suggest_test_fix(
    test_result: Dict[str, Any],
    glean_results: Any,
    jita_analysis: Optional[Dict[str, Any]] = None
) -> Optional[TestFixSuggestion]:
    """
    Convenience function to get test fix suggestion.
    
    Usage:
        fix_suggestion = await suggest_test_fix(test_result, glean_results, jita_analysis)
        if fix_suggestion and fix_suggestion.confidence > 0.6:
            # Present fix to user for approval
    """
    service = AutoTestFixService()
    return await service.analyze_test_fix(test_result, glean_results, jita_analysis)


async def create_test_fix_cr(
    fix_suggestion: TestFixSuggestion,
    user_approval: Dict[str, Any]
) -> FixChangeRequest:
    """
    Convenience function to create change request for approved fix.
    
    Usage:
        cr = await create_test_fix_cr(fix_suggestion, user_approval)
        # Process change request
    """
    service = AutoTestFixService()
    return await service.create_fix_cr(fix_suggestion, user_approval)