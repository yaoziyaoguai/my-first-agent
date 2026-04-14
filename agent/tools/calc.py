from agent.tool_registry import register_tool
import ast
import operator

SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
}

def _eval_node(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp):
        op_func = SAFE_OPS.get(type(node.op))
        if op_func is None:
            raise ValueError(f"不允许的运算符: {type(node.op).__name__}")
        return op_func(_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp):
        op_func = SAFE_OPS.get(type(node.op))
        if op_func is None:
            raise ValueError(f"不允许的运算符: {type(node.op).__name__}")
        return op_func(_eval_node(node.operand))
    raise ValueError(f"不允许的表达式类型: {type(node).__name__}")


@register_tool(
    name="calculate",
    description="计算一个数学表达式。仅在用户明确要求进行数学计算时使用。不要对文档内容、文件中出现的数字或表达式主动调用此工具。",
    parameters={
        "expression": {
            "type": "string",
            "description": "数学表达式，例如 '2 + 3 * 4'"
        }
    },
    confirmation="never",
)
def calculate(expression):
    try:
        tree = ast.parse(expression, mode='eval')
        result = _eval_node(tree.body)
        return str(result)
    except (ValueError, SyntaxError) as e:
        return f"计算错误：{e}"
    except ZeroDivisionError:
        return "计算错误：除数不能为零"
    except Exception as e:
        return f"计算错误：{e}"
