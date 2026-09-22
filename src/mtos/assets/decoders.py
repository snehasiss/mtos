"""Decoder maker choices and canonical model text."""

DECODER_MAKERS = {
    "unknown": "Unknown",
    "dcc_unknown": "DCC sound decoder (maker unknown)",
    "esu": "ESU",
    "soundtraxx": "SoundTraxx",
    "broadway_limited": "Broadway Limited",
    "qsi": "QSI",
    "digitrax": "Digitrax",
    "gaugemaster": "Gaugemaster",
    "bachmann": "Bachmann",
    "piko": "PIKO",
    "trix": "Trix",
    "nce": "NCE",
    "mrc": "MRC",
}

MODEL_ALIASES = {
    "loksound5": "loksound_5",
    "loksound v5": "loksound_5",
    "esu loksound v5": "loksound_5",
    "loksound": "loksound_unspecified",
    "esu loksound": "loksound_unspecified",
    "soundtraxx value": "sound_value",
    "smartdecoder5.1": "smartdecoder_5_1",
    "gm dcc92 4-function only": "dcc92",
    "bachmann 21 pin mtc": "21pin",
}


def canonical_decoder_maker(value):
    if value is None or value == "":
        return None
    if not isinstance(value, str) or value not in DECODER_MAKERS:
        raise ValueError(f"unsupported decoder maker: {value}")
    return value


def canonical_decoder_model(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("decoder model must be a string")
    value = value.strip().lower()
    if not value:
        return None
    value = MODEL_ALIASES.get(value, value.replace("-", "_").replace(" ", "_"))
    if not value.replace("_", "").replace(".", "").isalnum():
        raise ValueError("decoder model must use letters, numbers and underscores")
    return value
