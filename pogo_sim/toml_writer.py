"""把配置写成 TOML 文本（4f：网页导出配置、存进队伍库）。

标准库的 tomllib 只能读、不能写，这里只实现配置文件里用到的写法，不加依赖：
- 值：字符串、整数、小数、真假，以及由它们组成的列表（写在一行里）；
- 表（dict）写成 [表名]；全是表的非空列表写成 [[表名]]，可以嵌套（例如 [[team]] 下面的 [team.policy]、[[team.member]]）。

一个表里先写普通的键，再写子表，最后写表的列表（TOML 要求子表写在普通的键后面）。
空的表照样写出表头，所以读回来和原来完全相同（tests/test_toml_writer.py 核对）。
TOML 没有空值：遇到 None 或不支持的类型时报错，由调用的一方先去掉。
"""

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")
_ESCAPES = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\t": "\\t", "\n": "\\n", "\f": "\\f", "\r": "\\r"}


def dumps(data: Mapping[str, Any], header: Sequence[str] = ()) -> str:
    """整个文件的文本。header 是文件开头的注释，每行前面加 "# "。"""
    lines = [f"# {line}".rstrip() for line in header]
    body = _table_lines(data, ())
    if lines and body:
        lines.append("")
    lines += body
    return "\n".join(lines).rstrip() + "\n"


def _table_lines(table: Mapping[str, Any], path: tuple[str, ...]) -> list[str]:
    """一个表的内容（不含它自己的表头）。"""
    lines = []
    subtables = []
    arrays = []
    for key, value in table.items():
        if not isinstance(key, str):
            raise TypeError(f"{_dotted(path)}：键要是字符串，得到 {key!r}")
        if isinstance(value, Mapping):
            subtables.append((key, value))
        elif _is_array_of_tables(value):
            arrays.append((key, value))
        else:
            lines.append(f"{_key(key)} = {_value(value, (*path, key))}")
    for key, value in subtables:
        lines += ["", f"[{_dotted((*path, key))}]", *_table_lines(value, (*path, key))]
    for key, items in arrays:
        for item in items:
            lines += ["", f"[[{_dotted((*path, key))}]]", *_table_lines(item, (*path, key))]
    return lines


def _is_array_of_tables(value: Any) -> bool:
    return isinstance(value, list) and len(value) > 0 and all(isinstance(item, Mapping) for item in value)


def _value(value: Any, path: tuple[str, ...]) -> str:
    """写在一行里的值。"""
    if isinstance(value, bool):  # bool 是 int 的子类，要先判断
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{_dotted(path)}：不能写 {value!r}")
        return repr(value)
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, (list, tuple)):
        if any(isinstance(item, Mapping) for item in value):
            raise TypeError(f"{_dotted(path)}：列表里不能混着写表和别的值")
        return "[" + ", ".join(_value(item, path) for item in value) + "]"
    raise TypeError(f"{_dotted(path)}：TOML 写不了 {type(value).__name__} 类型的值 {value!r}")


def _string(text: str) -> str:
    """双引号字符串：引号、反斜杠和控制字符转义，其余（包括中文）原样。"""
    out = []
    for ch in text:
        if ch in _ESCAPES:
            out.append(_ESCAPES[ch])
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _key(key: str) -> str:
    return key if _BARE_KEY.match(key) else _string(key)


def _dotted(path: tuple[str, ...]) -> str:
    return ".".join(_key(key) for key in path)
