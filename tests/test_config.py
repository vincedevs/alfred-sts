import pytest

from alfred.config import PROJECT_ROOT, ConfigError, load_config


def test_defaults_need_only_the_api_key():
    config = load_config({"OPENAI_API_KEY": "sk-test"})
    assert config.live_model == "gpt-live-1"
    assert config.router_model == "gpt-6-luna"
    assert config.wakeword_dir == PROJECT_ROOT / "models"
    assert config.idle_seconds == 25.0
    assert config.input_device is None
    assert config.echo_cancellation is True


def test_missing_api_key_explains_the_fix():
    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        load_config({})


def test_values_are_parsed():
    config = load_config(
        {
            "OPENAI_API_KEY": "sk-test",
            "ALFRED_WAKE_THRESHOLD": "0.7",
            "ALFRED_IDLE_SECONDS": "40",
            "ALFRED_INPUT_DEVICE": "2",
            "ALFRED_OUTPUT_DEVICE": "MacBook Pro Speakers",
            "ALFRED_LOG_LEVEL": "debug",
        }
    )
    assert config.wake_threshold == 0.7
    assert config.idle_seconds == 40.0
    assert config.input_device == 2  # an index
    assert config.output_device == "MacBook Pro Speakers"  # part of a name
    assert config.log_level == "DEBUG"


@pytest.mark.parametrize("value", ["loud", "1.5"])
def test_bad_threshold_is_rejected(value):
    with pytest.raises(ConfigError, match="ALFRED_WAKE_THRESHOLD"):
        load_config({"OPENAI_API_KEY": "sk-test", "ALFRED_WAKE_THRESHOLD": value})


def test_prompt_files_exist():
    for name in ("voice", "router"):
        assert (PROJECT_ROOT / "prompts" / f"{name}.md").read_text().strip()


@pytest.mark.parametrize(("value", "expected"), [("off", False), ("ON", True), ("0", False)])
def test_echo_cancellation_switch(value, expected):
    config = load_config({"OPENAI_API_KEY": "sk-test", "ALFRED_ECHO_CANCELLATION": value})
    assert config.echo_cancellation is expected


def test_bad_switch_value_is_rejected():
    with pytest.raises(ConfigError, match="ALFRED_ECHO_CANCELLATION"):
        load_config({"OPENAI_API_KEY": "sk-test", "ALFRED_ECHO_CANCELLATION": "maybe"})
