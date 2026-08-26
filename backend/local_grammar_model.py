"""Optional free local grammar-correction model for PolyWrite.

The model is loaded lazily so the API still starts if the model cannot be
loaded. LanguageTool remains the reliable fallback.
"""
import logging
import os
import re

logger = logging.getLogger("polywrite")

_MODEL_NAME = os.environ.get(
    "POLYWRITE_GRAMMAR_MODEL", "vennify/t5-base-grammar-correction"
)
_model = None
_settings = None
_load_attempted = False


def _load_model():
    global _model, _settings, _load_attempted
    if _load_attempted:
        return _model
    _load_attempted = True
    try:
        from happytransformer import HappyTextToText, TTSettings
        _model = HappyTextToText("T5", _MODEL_NAME)
        _settings = TTSettings(num_beams=5, min_length=1, max_length=256)
        logger.info("Loaded local grammar model: %s", _MODEL_NAME)
    except Exception as exc:
        logger.warning("Local grammar model unavailable: %s", exc)
        _model = None
    return _model


def improve_text(text: str):
    """Return a model correction, or the original text when unavailable."""
    model = _load_model()
    if model is None:
        return text
    try:
        # T5 grammar-correction models conventionally expect the prefix below.
        prompt = "grammar: " + text
        result = model.generate_text(prompt, args=_settings)
        corrected = getattr(result, "text", "")
        corrected = re.sub(r"\s+", " ", corrected).strip()
        return corrected if corrected else text
    except Exception as exc:
        logger.warning("Local grammar correction failed: %s", exc)
        return text
