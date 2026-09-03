from routes.cookbook_routes import _serve_command_tool_support


def test_vllm_without_auto_tool_flags_records_unsupported():
    assert _serve_command_tool_support(
        "/app/.local/bin/vllm serve Qwen/Qwen3-8B --port 8000"
    ) is False


def test_vllm_with_auto_tool_flags_records_supported():
    assert _serve_command_tool_support(
        "vllm serve Qwen/Qwen3-8B --enable-auto-tool-choice "
        "--tool-call-parser qwen3_xml"
    ) is True


def test_sglang_without_auto_tool_flags_records_unsupported():
    assert _serve_command_tool_support(
        "python3 -m sglang.launch_server --model-path Qwen/Qwen3-8B"
    ) is False


def test_other_servers_leave_tool_support_unknown():
    assert _serve_command_tool_support("llama-server --model model.gguf") is None
