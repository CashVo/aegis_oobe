# aegis/agents/janus/engine.py
"""
Policy Evaluation Engine — Safe DSL interpreter for governance rules.

Implements: Part VI, §6.6 — Policy evaluation logic.

The engine evaluates policy conditions against a context dictionary using
a restricted, safe expression language. No arbitrary code execution.

Supported DSL:
  - Field references: context keys accessed directly (e.g., `action`, `resource`)
  - String comparison: ==, !=
  - Membership: `in`, `not_in` (checks if value is in a list)
  - String ops: `contains`, `startswith`, `endswith`
  - Logical: `and`, `or`, `not`
  - Grouping: parentheses
"""

import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)


class PolicyEvalError(Exception):
    """Raised when a policy condition cannot be safely evaluated."""
    pass


class PolicyEngine:
    """
    Evaluates policy rule conditions against a context dictionary.

    Uses a safe tokenized parser — does NOT use eval() or exec().
    """

    # Allowed operators in the DSL
    COMPARISON_OPS = {"==", "!=", "in", "not_in", "contains", "startswith", "endswith"}
    LOGICAL_OPS = {"and", "or", "not"}
    ALL_KEYWORDS = COMPARISON_OPS | LOGICAL_OPS | {"true", "false", "none"}

    def __init__(self):
        self._cache: dict[str, list] = {}  # Parsed token cache

    def evaluate(self, condition: str, context: dict[str, Any]) -> bool:
        """
        Evaluate a condition string against the provided context.

        Args:
            condition: DSL condition string.
            context: Dictionary of context values to evaluate against.

        Returns:
            True if condition matches, False otherwise.

        Raises:
            PolicyEvalError: If the condition is malformed or unsafe.
        """
        try:
            tokens = self._tokenize(condition)
            result, _ = self._parse_expression(tokens, 0, context)
            return result
        except PolicyEvalError:
            raise
        except Exception as e:
            logger.error(f"Policy evaluation failed for condition: {condition!r}, error: {e}")
            raise PolicyEvalError(f"Failed to evaluate condition: {condition!r}") from e

    def _tokenize(self, condition: str) -> list[str]:
        """Tokenize a condition string into a list of tokens."""
        if condition in self._cache:
            return self._cache[condition]

        # Pattern: quoted strings, parentheses, operators, identifiers, list brackets, commas
        pattern = r"""
            ("[^"]*"|'[^']*')    |  # Quoted strings
            (\(|\))              |  # Parentheses
            (\[|\])              |  # List brackets
            (,)                  |  # Commas
            (==|!=)              |  # Comparison operators
            ([a-zA-Z_][a-zA-Z0-9_.]*)  |  # Identifiers and keywords
            (\S+)                   # Catch-all for unexpected tokens
        """
        tokens = []
        for match in re.finditer(pattern, condition, re.VERBOSE):
            token = match.group(0).strip()
            if token:
                tokens.append(token)

        self._cache[condition] = tokens
        return tokens

    def _parse_expression(
        self, tokens: list[str], pos: int, context: dict[str, Any]
    ) -> tuple[bool, int]:
        """Parse a full expression with logical operators (and/or)."""
        left, pos = self._parse_not(tokens, pos, context)

        while pos < len(tokens) and tokens[pos] in ("and", "or"):
            op = tokens[pos]
            pos += 1
            right, pos = self._parse_not(tokens, pos, context)

            if op == "and":
                left = left and right
            elif op == "or":
                left = left or right

        return left, pos

    def _parse_not(
        self, tokens: list[str], pos: int, context: dict[str, Any]
    ) -> tuple[bool, int]:
        """Handle 'not' prefix."""
        if pos < len(tokens) and tokens[pos] == "not":
            pos += 1
            result, pos = self._parse_not(tokens, pos, context)
            return not result, pos
        return self._parse_comparison(tokens, pos, context)

    def _parse_comparison(
        self, tokens: list[str], pos: int, context: dict[str, Any]
    ) -> tuple[bool, int]:
        """Parse a comparison expression or grouped expression."""
        # Handle parenthesized groups
        if pos < len(tokens) and tokens[pos] == "(":
            pos += 1  # skip '('
            result, pos = self._parse_expression(tokens, pos, context)
            if pos < len(tokens) and tokens[pos] == ")":
                pos += 1  # skip ')'
            else:
                raise PolicyEvalError("Unmatched parenthesis in condition.")
            return result, pos

        # Get left operand
        left_val, pos = self._resolve_value(tokens, pos, context)

        # Check for comparison operator
        if pos < len(tokens) and tokens[pos] in self.COMPARISON_OPS:
            op = tokens[pos]
            pos += 1
            right_val, pos = self._resolve_value(tokens, pos, context)

            result = self._apply_comparison(left_val, op, right_val)
            return result, pos

        # Bare truthy check
        return bool(left_val), pos

    def _resolve_value(
        self, tokens: list[str], pos: int, context: dict[str, Any]
    ) -> tuple[Any, int]:
        """Resolve a token to its value (literal, context lookup, or list)."""
        if pos >= len(tokens):
            raise PolicyEvalError("Unexpected end of condition expression.")

        token = tokens[pos]

        # List literal: [item1, item2, ...]
        if token == "[":
            return self._parse_list(tokens, pos, context)

        # String literal (quoted)
        if (token.startswith('"') and token.endswith('"')) or            (token.startswith("'") and token.endswith("'")):
            return token[1:-1], pos + 1

        # Boolean literals
        if token.lower() == "true":
            return True, pos + 1
        if token.lower() == "false":
            return False, pos + 1
        if token.lower() == "none":
            return None, pos + 1

        # Numeric literals
        try:
            if "." in token:
                return float(token), pos + 1
            return int(token), pos + 1
        except ValueError:
            pass

        # Context field reference (supports dot notation)
        if re.match(r'^[a-zA-Z_][a-zA-Z0-9_.]*$', token) and token not in self.ALL_KEYWORDS:
            value = self._resolve_context_field(token, context)
            return value, pos + 1

        # If it looks like a keyword that shouldn't be here, error
        if token in self.LOGICAL_OPS or token in (")", "]", ","):
            raise PolicyEvalError(f"Unexpected token in value position: {token!r}")

        raise PolicyEvalError(f"Cannot resolve token: {token!r}")

    def _parse_list(
        self, tokens: list[str], pos: int, context: dict[str, Any]
    ) -> tuple[list, int]:
        """Parse a list literal [item1, item2, ...]."""
        pos += 1  # skip '['
        items = []
        while pos < len(tokens) and tokens[pos] != "]":
            if tokens[pos] == ",":
                pos += 1
                continue
            val, pos = self._resolve_value(tokens, pos, context)
            items.append(val)
        if pos < len(tokens) and tokens[pos] == "]":
            pos += 1  # skip ']'
        else:
            raise PolicyEvalError("Unmatched bracket in list literal.")
        return items, pos

    def _resolve_context_field(self, field: str, context: dict[str, Any]) -> Any:
        """
        Resolve a dotted field reference against the context dict.

        Example: 'request.action' resolves context['request']['action']
        """
        parts = field.split(".")
        value: Any = context

        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return None

        return value

    def _apply_comparison(self, left: Any, op: str, right: Any) -> bool:
        """Apply a comparison operator between two resolved values."""
        if op == "==":
            return left == right
        elif op == "!=":
            return left != right
        elif op == "in":
            if isinstance(right, (list, tuple, set)):
                return left in right
            if isinstance(right, str):
                return str(left) in right
            return False
        elif op == "not_in":
            if isinstance(right, (list, tuple, set)):
                return left not in right
            if isinstance(right, str):
                return str(left) not in right
            return True
        elif op == "contains":
            if isinstance(left, str) and isinstance(right, str):
                return right in left
            if isinstance(left, (list, tuple, set)):
                return right in left
            return False
        elif op == "startswith":
            if isinstance(left, str) and isinstance(right, str):
                return left.startswith(right)
            return False
        elif op == "endswith":
            if isinstance(left, str) and isinstance(right, str):
                return left.endswith(right)
            return False
        else:
            raise PolicyEvalError(f"Unknown comparison operator: {op!r}")

    def clear_cache(self) -> None:
        """Clear the tokenization cache."""
        self._cache.clear()
