"""Basic arithmetic calculator CLI.

Usage: python calculator.py <operand1> <operator> <operand2>

Operators: + - * /  (quote * so the shell does not expand it: '*')
"""
import math
import sys

USAGE = "Usage: calculator.py <operand1> <operator> <operand2>  (operators: + - '*' /)"


def add(a, b):
    return a + b


def subtract(a, b):
    return a - b


def multiply(a, b):
    return a * b


def divide(a, b):
    if b == 0:
        raise ZeroDivisionError("division by zero")
    return a / b


OPERATIONS = {"+": add, "-": subtract, "*": multiply, "/": divide}


def parse_number(text):
    try:
        return int(text)
    except ValueError:
        value = float(text)
        if not math.isfinite(value):
            raise ValueError(text)
        return value


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 3:
        print(USAGE, file=sys.stderr)
        return 2
    left, op, right = argv
    if op not in OPERATIONS:
        print(f"Error: unknown operator '{op}'", file=sys.stderr)
        return 2
    operands = []
    for text in (left, right):
        try:
            operands.append(parse_number(text))
        except ValueError:
            print(f"Error: invalid number '{text}'", file=sys.stderr)
            return 1
    a, b = operands
    try:
        result = OPERATIONS[op](a, b)
    except ZeroDivisionError:
        print("Error: division by zero", file=sys.stderr)
        return 1
    except OverflowError:
        print("Error: result too large", file=sys.stderr)
        return 1
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
