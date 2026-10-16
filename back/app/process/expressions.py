"""Deterministic, non-executable expressions for the Galaris BPMN profile."""

from __future__ import annotations

import ast
import operator
from collections.abc import Mapping, Callable
from typing import Any, cast


class ExpressionError(ValueError):
    pass


_BINARY: dict[type[ast.operator], Callable[[Any, Any], Any]] = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: lambda a, b: a / b, ast.Mod: operator.mod}
_COMPARE: dict[type[ast.cmpop], Callable[[Any, Any], bool]] = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
            ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge,
            ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b}


def parse_expression(expression: str) -> ast.Expression:
    """Validate every branch, including branches which short circuit at runtime."""
    if len(expression) > 10_000:
        raise ExpressionError("Expression exceeds the parser size limit")
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, RecursionError) as error:
        raise ExpressionError("Invalid expression") from error
    if sum(1 for _ in ast.walk(tree)) > 512:
        raise ExpressionError("Expression exceeds the parser complexity limit")
    allowed = (ast.Expression, ast.Constant, ast.Name, ast.Load, ast.Attribute, ast.Subscript,
        ast.List, ast.Tuple, ast.Dict, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not,
        ast.USub, ast.BinOp, *tuple(_BINARY), ast.Compare, *tuple(_COMPARE))
    for node in ast.walk(tree):
        if not isinstance(node, allowed) or isinstance(node, ast.Name) and node.id.startswith("_") or isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise ExpressionError("Unsupported expression syntax")
        if isinstance(node, ast.Dict) and any(key is None for key in node.keys):
            raise ExpressionError("Dictionary expansion is not supported")
    return tree


def evaluate(expression: str, context: Mapping[str, Any]) -> Any:
    """Interpret a bounded syntax tree. Missing paths are null; calls are forbidden."""
    tree = parse_expression(expression)

    def visit(node: ast.AST) -> Any:
        if isinstance(node, ast.Constant) and isinstance(node.value, (str, int, float, bool, type(None))):
            return node.value
        if isinstance(node, ast.Name) and not node.id.startswith("_"):
            return {"null": None, "true": True, "false": False}.get(node.id, context.get(node.id))
        if isinstance(node, ast.Attribute) and not node.attr.startswith("_"):
            value = visit(node.value)
            return cast(dict[str, Any], value).get(node.attr) if isinstance(value, dict) else None
        if isinstance(node, ast.Subscript):
            value, key = visit(node.value), visit(node.slice)
            if isinstance(value, dict):
                return cast(dict[str, Any], value).get(key)
            if isinstance(value, (list, str)) and isinstance(key, int):
                value = cast(list[Any] | str, value)
                return value[key] if -len(value) <= key < len(value) else None
            return None
        if isinstance(node, (ast.List, ast.Tuple)):
            return [visit(element) for element in node.elts]
        if isinstance(node, ast.Dict):
            return {visit(key): visit(value) for key, value in zip(node.keys, node.values) if key is not None}
        if isinstance(node, ast.BoolOp):
            values = node.values
            result: Any = None
            for value in values:
                result = visit(value)
                if isinstance(node.op, ast.And) and not result or isinstance(node.op, ast.Or) and result:
                    break
            return result
        if isinstance(node, ast.UnaryOp):
            value = visit(node.operand)
            if isinstance(node.op, ast.Not):
                return not value
            if isinstance(node.op, ast.USub) and isinstance(value, (int, float)) and not isinstance(value, bool):
                return -value
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            left, right = visit(node.left), visit(node.right)
            if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
                raise ExpressionError("Arithmetic requires numbers")
            return _BINARY[type(node.op)](left, right)
        if isinstance(node, ast.Compare):
            left = visit(node.left)
            for op, right_node in zip(node.ops, node.comparators):
                operation = _COMPARE.get(type(op))
                if operation is None:
                    raise ExpressionError("Unsupported comparison")
                right = visit(right_node)
                if not operation(left, right):
                    return False
                left = right
            return True
        raise ExpressionError("Unsupported expression syntax")

    try:
        return visit(tree.body)
    except (TypeError, KeyError, ZeroDivisionError, OverflowError, RecursionError) as error:
        raise ExpressionError("Expression cannot be evaluated for these inputs") from error


def resolve(value: Any, context: Mapping[str, Any]) -> Any:
    """JSON mappings use an explicit {$expr: expression} leaf, never interpolation."""
    if isinstance(value, dict):
        value = cast(dict[str, Any], value)
        if set(value) == {"$expr"} and isinstance(value["$expr"], str):
            return evaluate(value["$expr"], context)
        return {key: resolve(child, context) for key, child in value.items()}
    if isinstance(value, list):
        value = cast(list[Any], value)
        return [resolve(child, context) for child in value]
    return value
