"""
LLM model configurations.
"""

# Supported Gemini models with their full identifiers
GEMINI_MODELS = {
    "flash": "gemini-2.0-flash",           # Best for free tier (15 RPM)
    "flash-lite": "gemini-2.0-flash-lite", # Even faster/cheaper
    "pro": "gemini-2.5-pro-preview-06-05", # Best quality, limited free tier
}

# Default model for API calls
DEFAULT_MODEL = "flash"

# Model-specific configuration
MODEL_CONFIG = {
    "flash": {
        "max_output_tokens": 65536,
        "temperature": 0.0,  # Deterministic responses
        "seed": 42,  # Seed for deterministic generation
    },
    "flash-lite": {
        "max_output_tokens": 32768,
        "temperature": 0.0,  # Deterministic responses
        "seed": 42,  # Seed for deterministic generation
    },
    "pro": {
        "max_output_tokens": 65536,
        "temperature": 0.0,  # Deterministic responses
        "seed": 42,  # Seed for deterministic generation
    },
}


def get_model_config(model_name: str) -> dict:
    """
    Get configuration for a specific model.
    
    Args:
        model_name: Short model name (flash, flash-lite, pro).
        
    Returns:
        Configuration dict with max_output_tokens, temperature, etc.
    """
    return MODEL_CONFIG.get(model_name, MODEL_CONFIG["flash"])

