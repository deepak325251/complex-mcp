import json

from scripts.task_writer import parse_trajectory, _slug, write_task_dir


def test_slug_strips_complexmcp_prefix_and_suffix():
    assert _slug("complexmcp-l1-s42-like-the-latest-post-000") == "like-the-latest-post"


def test_slug_truncates_at_maxlen():
    long = "complexmcp-l1-s1-" + "a" * 200 + "-000"
    assert len(_slug(long, maxlen=40)) == 40


def test_slug_empty_fallback():
    assert _slug("---") == "task"


def test_parse_trajectory_single_tool_and_response():
    output = (
        "I'll look this up.\n"
        '<tool>\n{"name": "get_uid_from_name", "arguments": {"name": "Jeremy"}}\n</tool>\n'
        '<response>\n{"status":"ok","output":"user_XYZ"}\n</response>\n'
        "Done. [END]"
    )
    traj = parse_trajectory(output)
    assert len(traj["steps"]) == 1
    step = traj["steps"][0]
    assert step["tool"] == "get_uid_from_name"
    assert step["arguments"] == {"name": "Jeremy"}
    assert step["response"] == {"status": "ok", "output": "user_XYZ"}
    assert "Done." in traj["final_message"]


def test_parse_trajectory_no_tools():
    traj = parse_trajectory("I refuse to help with that.")
    assert traj["steps"] == []
    assert traj["final_message"] == "I refuse to help with that."


def test_parse_trajectory_multiple_steps():
    output = (
        '<tool>{"name":"a","arguments":{}}</tool><response>{"status":"ok"}</response>'
        '<tool>{"name":"b","arguments":{}}</tool><response>{"status":"ok"}</response>'
    )
    traj = parse_trajectory(output)
    assert [s["tool"] for s in traj["steps"]] == ["a", "b"]


def test_write_task_dir_creates_all_files(tmp_path):
    record = {
        "index": 1,
        "name": "complexmcp-l1-s42-like-the-latest-post-000",
        "query": "Like the latest post",
        "seed": 42,
        "apps": ["LightTalk"],
        "level": 1,
        "tool_cnt": {"like_moment": {"ok": 1}},
        "tokens": {"prompt": 4, "llm": 100, "tool": 50},
        "valid_tool_calls": 1,
        "invalid_tool_calls": 0,
        "error_tool_calls": 0,
        "output": '<tool>{"name":"like_moment","arguments":{}}</tool><response>{"status":"ok"}</response>[END]',
    }
    score = {"gradeable": True, "passed": True, "reward": 1.0,
             "recall": 1, "total": 1, "misbehave": 0}
    task_dir, final_score = write_task_dir(tmp_path, record, score=score)
    assert task_dir.is_dir()
    for f in ("meta.json", "output.md", "trajectory.json",
              "tool_summary.json", "tokens.json", "score.json"):
        assert (task_dir / f).exists(), f
    meta = json.loads((task_dir / "meta.json").read_text())
    assert meta["seed"] == 42
    assert meta["name"] == record["name"]
    assert final_score.get("passed") is True


def test_write_task_dir_classifies_failure(tmp_path):
    record = {
        "index": 2,
        "name": "complexmcp-l1-s42-search-only-000",
        "query": "like a post",
        "seed": 42,
        "apps": ["LightTalk"],
        "level": 1,
        "tool_cnt": {"search_products": {"ok": 1}},
        "tokens": {"prompt": 4, "llm": 100, "tool": 50},
        "valid_tool_calls": 1,
        "invalid_tool_calls": 0,
        "error_tool_calls": 0,
        "output": '<tool>{"name":"search_products","arguments":{}}</tool><response>{"status":"ok"}</response>',
    }
    score = {"gradeable": True, "passed": False, "reward": 0.0,
             "recall": 0, "total": 1, "misbehave": 0}
    context = {"expected_tools": ["like_moment", "get_uid_from_name"]}
    _, final_score = write_task_dir(tmp_path, record, score=score, task_context=context)
    assert final_score.get("failure_class") == "wrong_tool"
