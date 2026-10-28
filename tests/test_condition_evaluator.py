"""
Unit tests for condition evaluation and variable interpolation.
"""

import pytest
from newdoauto.core.state import ExecutionContext
from newdoauto.core.evaluator import evaluate_condition, interpolate_variables


def test_variable_interpolation():
    ctx = ExecutionContext()
    ctx.set_variable("user", "Alice")
    ctx.set_variable("score", 95)
    ctx.set_action_result("step1", "result_abc")

    # Simple string interpolation
    assert interpolate_variables("Hello, ${user}!", ctx) == "Hello, Alice!"
    assert interpolate_variables("Score: ${score}", ctx) == "Score: 95"
    assert interpolate_variables("Output: ${step1}", ctx) == "Output: result_abc"

    # Exact variable returns native type
    assert interpolate_variables("${score}", ctx) == 95

    # Dict and list recursive interpolation
    data = {
        "greeting": "Hi ${user}",
        "items": ["${score}", "fixed"],
    }
    interp_data = interpolate_variables(data, ctx)
    assert interp_data["greeting"] == "Hi Alice"
    assert interp_data["items"] == [95, "fixed"]


def test_string_condition_comparisons():
    ctx = ExecutionContext()
    ctx.set_variable("status", "ACTIVE")
    ctx.set_variable("count", 15)
    ctx.set_variable("msg", "Error 404: Not Found")

    # Equality & Inequality
    assert evaluate_condition("${status} == 'ACTIVE'", ctx) is True
    assert evaluate_condition("${status} == 'INACTIVE'", ctx) is False
    assert evaluate_condition("${status} != 'INACTIVE'", ctx) is True

    # Numeric comparisons
    assert evaluate_condition("${count} > 10", ctx) is True
    assert evaluate_condition("${count} < 5", ctx) is False
    assert evaluate_condition("${count} >= 15", ctx) is True
    assert evaluate_condition("${count} <= 14", ctx) is False

    # String predicates
    assert evaluate_condition("${msg} contains '404'", ctx) is True
    assert evaluate_condition("${msg} not contains '500'", ctx) is True
    assert evaluate_condition("${msg} startswith 'Error'", ctx) is True
    assert evaluate_condition("${msg} endswith 'Found'", ctx) is True


def test_structured_dictionary_conditions():
    ctx = ExecutionContext()
    ctx.set_variable("observed", "NewDoAuto_POC_2026")

    cond1 = {
        "left": "${observed}",
        "operator": "equals",
        "right": "NewDoAuto_POC_2026",
    }
    assert evaluate_condition(cond1, ctx) is True

    cond2 = {
        "left": "${observed}",
        "operator": "contains",
        "right": "POC",
    }
    assert evaluate_condition(cond2, ctx) is True

    cond3 = {
        "left": "${observed}",
        "operator": "equals",
        "right": "WRONG_STRING",
    }
    assert evaluate_condition(cond3, ctx) is False


def test_boolean_literals():
    ctx = ExecutionContext()
    assert evaluate_condition("True", ctx) is True
    assert evaluate_condition("False", ctx) is False
    assert evaluate_condition("1 == 1", ctx) is True
    assert evaluate_condition("1 == 2", ctx) is False
