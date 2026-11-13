import pytest
from financial.ingestion.alpha_vantage.config import (
    AlphaVantageConfig,
    EconomicIndicator,
)
from pydantic import ValidationError

KEY = "TESTKEY123SECRET"  # pragma: allowlist secret


def make(**overrides):
    return AlphaVantageConfig.model_validate(
        {"api_key": KEY, "symbols": ["jnj"], **overrides}
    )


def test_api_key_is_masked_in_repr_and_str():
    config = make()
    assert KEY not in repr(config)
    assert KEY not in str(config)
    assert config.api_key.get_secret_value() == KEY


@pytest.mark.parametrize("key", ["", "   ", "<paste-your-alpha-vantage-api-key-here>"])
def test_rejects_missing_or_placeholder_api_key(key):
    with pytest.raises(ValidationError, match="placeholder"):
        make(api_key=key)


def test_validation_errors_do_not_echo_the_api_key():
    # Fails on symbols, but the error must not include any input, including the key
    with pytest.raises(ValidationError) as excinfo:
        make(symbols=["not a symbol"])
    assert KEY not in str(excinfo.value)


def test_symbols_are_normalised_to_upper_case():
    assert make(symbols=[" jnj ", "brk.b"]).symbols == ("JNJ", "BRK.B")


@pytest.mark.parametrize(
    "symbols", [[], ["JNJ", "jnj"], ["NOT A SYMBOL"], ["WAYTOOLONGSYMBOL"]]
)
def test_rejects_invalid_symbols(symbols):
    with pytest.raises(ValidationError):
        make(symbols=symbols)


def test_rejects_unknown_outputsize():
    with pytest.raises(ValidationError):
        make(outputsize="everything")


def test_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        make(sybmols=["JNJ"])


def test_indicator_params_omit_unset_values():
    assert EconomicIndicator(function="INFLATION").params() == {}
    assert EconomicIndicator(
        function="TREASURY_YIELD", interval="weekly", maturity="2year"
    ).params() == {"interval": "weekly", "maturity": "2year"}


@pytest.mark.parametrize(
    "indicator",
    [
        {"function": "NOT_A_FUNCTION"},
        {
            "function": "REAL_GDP",
            "interval": "monthly",
        },  # REAL_GDP is annual/quarterly only
        {"function": "UNEMPLOYMENT", "interval": "monthly"},  # takes no interval
        {"function": "CPI", "maturity": "10year"},  # maturity is TREASURY_YIELD only
    ],
)
def test_rejects_invalid_indicators(indicator):
    with pytest.raises(ValidationError):
        make(indicators=[indicator])


def test_indicator_code_adds_the_maturity():
    assert EconomicIndicator(function="CPI").code == "CPI"
    assert (
        EconomicIndicator(function="TREASURY_YIELD", maturity="3month").code
        == "TREASURY_YIELD_3MONTH"
    )


def test_accepts_one_function_at_several_maturities():
    # Each maturity is its own series, with its own code in the primary key
    settings = make(
        indicators=[
            {"function": "TREASURY_YIELD", "maturity": "3month"},
            {"function": "TREASURY_YIELD", "maturity": "10year"},
        ]
    )
    assert [i.code for i in settings.indicators] == [
        "TREASURY_YIELD_3MONTH",
        "TREASURY_YIELD_10YEAR",
    ]


def test_rejects_duplicate_indicator_series():
    # (indicator, date) is the primary key, so the same series twice would collide
    with pytest.raises(ValidationError, match="duplicate indicator series"):
        make(
            indicators=[
                {"function": "TREASURY_YIELD", "maturity": "2year"},
                {
                    "function": "TREASURY_YIELD",
                    "interval": "weekly",
                    "maturity": "2year",
                },
            ]
        )


def test_redact_masks_the_key_in_arbitrary_text():
    assert (
        make().redact(f"key {KEY} is rate limited") == "key ********** is rate limited"
    )
