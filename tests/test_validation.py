"""
Tests for validation module.
"""

import json
import tempfile
from pathlib import Path

import pytest

from src.validation import (
    ValidationError,
    ConfigurationError,
    validate_path_exists,
    validate_file_readable,
    validate_json_file,
    validate_state_file,
    validate_policy_dir,
    validate_deadline_iso,
    validate_escalation_state,
)


class TestValidationError:
    """Tests for ValidationError exception."""

    def test_basic_message(self):
        """Error with just a message."""
        err = ValidationError("Something went wrong")
        assert str(err) == "Something went wrong"

    def test_message_with_field(self):
        """Error with field and message."""
        err = ValidationError("is required", field="deadline_iso")
        assert str(err) == "deadline_iso: is required"

    def test_message_with_details(self):
        """Error with extra details."""
        err = ValidationError("failed", details={"code": 123})
        assert err.details == {"code": 123}


class TestValidatePath:
    """Tests for path validation."""

    def test_existing_path_passes(self, tmp_path):
        """Existing path passes validation."""
        validate_path_exists(tmp_path, "Test directory")

    def test_nonexistent_path_fails(self):
        """Nonexistent path raises ValidationError."""
        fake_path = Path("/nonexistent/path/abc123")
        with pytest.raises(ValidationError) as exc_info:
            validate_path_exists(fake_path, "Test path")
        assert "does not exist" in str(exc_info.value)


class TestValidateFile:
    """Tests for file validation."""

    def test_readable_file_passes(self, tmp_path):
        """Readable file passes validation."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")
        validate_file_readable(test_file, "Test file")

    def test_directory_fails(self, tmp_path):
        """Directory fails file validation."""
        with pytest.raises(ValidationError) as exc_info:
            validate_file_readable(tmp_path, "Test file")
        assert "not a file" in str(exc_info.value)


class TestValidateJson:
    """Tests for JSON file validation."""

    def test_valid_json_loads(self, tmp_path):
        """Valid JSON file is loaded correctly."""
        json_file = tmp_path / "test.json"
        json_file.write_text('{"key": "value", "num": 42}')
        
        result = validate_json_file(json_file, "Test JSON")
        
        assert result["key"] == "value"
        assert result["num"] == 42

    def test_invalid_json_fails(self, tmp_path):
        """Invalid JSON raises ValidationError."""
        json_file = tmp_path / "bad.json"
        json_file.write_text('{"key": invalid}')
        
        with pytest.raises(ValidationError) as exc_info:
            validate_json_file(json_file, "Test JSON")
        assert "Invalid JSON" in str(exc_info.value)


class TestValidateStateFile:
    """Tests for state file validation."""

    def test_valid_state_file(self, tmp_path):
        """Valid state file passes validation."""
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({
            "meta": {"state_id": "S-001", "updated_at_iso": "2026-01-01T00:00:00Z"},
            "mode": {"name": "renewable_countdown", "armed": True},
            "timer": {"deadline_iso": "2026-02-01T00:00:00Z"},
            "escalation": {"state": "OK"},
        }))
        
        result = validate_state_file(state_file)
        
        assert result["meta"]["state_id"] == "S-001"

    def test_missing_required_keys(self, tmp_path):
        """State file missing keys fails."""
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({
            "meta": {"state_id": "S-001"},
            # Missing: mode, timer, escalation
        }))
        
        with pytest.raises(ValidationError) as exc_info:
            validate_state_file(state_file)
        assert "Missing required keys" in str(exc_info.value)

    def test_missing_state_id(self, tmp_path):
        """State file without state_id fails."""
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({
            "meta": {},  # No state_id
            "mode": {},
            "timer": {"deadline_iso": "2026-01-01T00:00:00Z"},
            "escalation": {},
        }))
        
        with pytest.raises(ValidationError) as exc_info:
            validate_state_file(state_file)
        assert "state_id" in str(exc_info.value)


class TestValidatePolicyDir:
    """Tests for policy directory validation."""

    def test_valid_policy_dir(self, tmp_path):
        """Valid policy directory passes validation."""
        # Create policy structure
        (tmp_path / "states.yaml").write_text("states: []")
        (tmp_path / "rules.yaml").write_text("rules: []")
        plans_dir = tmp_path / "plans"
        plans_dir.mkdir()
        (plans_dir / "default.yaml").write_text("stages: {}")
        
        result = validate_policy_dir(tmp_path)
        
        assert "states" in result
        assert "rules" in result
        assert "plans" in result

    def test_missing_states_yaml(self, tmp_path):
        """Missing states.yaml fails."""
        (tmp_path / "rules.yaml").write_text("rules: []")
        plans_dir = tmp_path / "plans"
        plans_dir.mkdir()
        (plans_dir / "default.yaml").write_text("stages: {}")
        
        with pytest.raises(ValidationError) as exc_info:
            validate_policy_dir(tmp_path)
        assert "states.yaml" in str(exc_info.value)

    def test_missing_plans_dir(self, tmp_path):
        """Missing plans directory fails."""
        (tmp_path / "states.yaml").write_text("states: []")
        (tmp_path / "rules.yaml").write_text("rules: []")
        
        with pytest.raises(ValidationError) as exc_info:
            validate_policy_dir(tmp_path)
        assert "Plans directory" in str(exc_info.value)


class TestValidateDeadline:
    """Tests for deadline validation."""

    def test_valid_iso_date(self):
        """Valid ISO datetime passes."""
        assert validate_deadline_iso("2026-02-04T12:00:00Z") is True

    def test_valid_iso_with_offset(self):
        """ISO datetime with offset passes."""
        assert validate_deadline_iso("2026-02-04T12:00:00-05:00") is True

    def test_invalid_format(self):
        """Invalid format fails."""
        with pytest.raises(ValidationError) as exc_info:
            validate_deadline_iso("not-a-date")
        assert "Invalid ISO datetime" in str(exc_info.value)


class TestValidateEscalationState:
    """Tests for escalation state validation."""

    def test_valid_state(self):
        """Valid state passes."""
        valid_states = ["OK", "REMIND_1", "REMIND_2", "FULL"]
        assert validate_escalation_state("REMIND_1", valid_states) is True

    def test_invalid_state(self):
        """Invalid state fails."""
        valid_states = ["OK", "REMIND_1", "REMIND_2", "FULL"]
        with pytest.raises(ValidationError) as exc_info:
            validate_escalation_state("INVALID", valid_states)
        assert "Invalid escalation state" in str(exc_info.value)
