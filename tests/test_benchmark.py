"""Benchmark mode stays "almost exactly" Alfred: the same prompts minus the switched-off
features, and the same GPT-Live settings."""

import sys

import pytest

from alfred.config import PROJECT_ROOT, Config, load_prompt

sys.path.insert(0, str(PROJECT_ROOT))  # benchmark/ isn't part of the installed package

from benchmark.prompts import (  # noqa: E402
    LEFT_OUT,
    THIS_SESSION,
    benchmark_prompt,
    without_sections,
)


@pytest.mark.parametrize("name", ["voice", "router"])
def test_benchmark_prompts_are_alfreds_minus_the_switched_off_sections(name):
    real = load_prompt(name)
    for heading in LEFT_OUT[name]:
        assert f"## {heading}\n" in real, f"prompts/{name}.md has no '## {heading}' any more"
    trimmed = benchmark_prompt(name)
    assert trimmed.endswith(THIS_SESSION)
    kept = trimmed.removesuffix(THIS_SESSION)
    assert all(line in real.splitlines() for line in kept.splitlines())  # nothing new or edited
    for heading in LEFT_OUT[name]:
        assert f"## {heading}" not in kept
    assert len(kept) < len(real)


def test_without_sections_keeps_everything_else():
    text = "Intro\n\n## Keep\nA\n\n## Drop\nB\nC\n\n## Also keep\nD"
    assert without_sections(text, ["Drop"]) == "Intro\n\n## Keep\nA\n\n## Also keep\nD"


def test_benchmark_entry_uses_16_khz():
    from benchmark.assistant_entry import PROJECT_MARKER, audio_rates

    assert audio_rates() == (16000, 16000)
    assert (PROJECT_ROOT / PROJECT_MARKER).is_file()


def test_benchmark_gpt_live_is_built_by_alfreds_own_code():
    pytest.importorskip("pipecat.services.openai.live.llm")
    import alfred.voice as alfred_voice
    from benchmark.voice import create_gpt_live

    built = []
    real_create = alfred_voice.create_gpt_live

    def spy(config, voice_extra, router_extra):
        built.append((alfred_voice.load_prompt("router"), voice_extra))
        return real_create(config, voice_extra, router_extra)

    alfred_voice.create_gpt_live = spy
    try:
        create_gpt_live(Config(openai_api_key="sk-test"))
    finally:
        alfred_voice.create_gpt_live = real_create
    router_prompt, extra = built[0]
    assert "## Memory" not in router_prompt and THIS_SESSION.strip() in router_prompt
    assert "Manila" in extra
    assert alfred_voice.load_prompt is load_prompt  # put back afterwards
