"""把配置写成 TOML（pogo_sim/toml_writer.py）：写出去再用标准库 tomllib 读回来，和原来完全相同。"""

import tomllib

import pytest

from pogo_sim.config import REPO_ROOT, load_toml
from pogo_sim.toml_writer import dumps


def roundtrip(data):
    return tomllib.loads(dumps(data))


def test_values():
    data = {
        "text": "中文 and \"quotes\" \\ back\tslash\nnew line \x01",
        "int": -3,
        "float": 0.25,
        "big": 1e20,
        "yes": True,
        "no": False,
        "list": [1, 2, 3],
        "strings": ["a", "b c"],
        "empty": [],
        "nested_list": [[1, 2], ["x"]],
    }
    assert roundtrip(data) == data


def test_tables_and_arrays_of_tables():
    data = {
        "league": 1500,
        "policy": {"switching": "never", "moves": {"bait_shields": False}},
        "team": [
            {"name": "A", "policy": {}, "member": [{"species": "x", "charged": ["M1"]}, {"species": "y", "charged": []}]},
            {"name": "B", "member": [{"species": "z", "ivs": [0, 15, 15], "level": 20.5}]},
        ],
        "empty_table": {},
    }
    assert roundtrip(data) == data


def test_layout():
    """普通的键在前，子表其次，表的列表最后；开头的注释。"""
    text = dumps({"team": [{"member": [{"a": 1}], "name": "A", "policy": {"s": "t"}}], "league": 1}, ["说明", ""])
    assert text == (
        "# 说明\n"
        "#\n"
        "\n"
        "league = 1\n"
        "\n"
        "[[team]]\n"
        'name = "A"\n'
        "\n"
        "[team.policy]\n"
        's = "t"\n'
        "\n"
        "[[team.member]]\n"
        "a = 1\n"
    )


def test_keys_that_need_quotes():
    data = {"a b": 1, "中文": {"x.y": 2}}
    text = dumps(data)
    assert '"a b" = 1' in text and '["中文"]' in text and '"x.y" = 2' in text
    assert roundtrip(data) == data


@pytest.mark.parametrize("value", [None, {1, 2}, float("nan"), [1, {"a": 1}]])
def test_unsupported_values(value):
    with pytest.raises((TypeError, ValueError)):
        dumps({"x": value})


@pytest.mark.parametrize("name", ["gl_3v3_example.toml", "gl_team_matrix_example.toml", "mega_zygarde_ml.toml"])
def test_example_configs_roundtrip(name):
    """仓库里的配置文件读进来、写出去、再读回来，内容不变。"""
    data = load_toml(REPO_ROOT / "experiments" / name)
    assert roundtrip(data) == data
