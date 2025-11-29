"""
Gemini API client for the HDD Folder Restructure Tool.
"""

import json
import os
import re
from typing import Any

from .models import GEMINI_MODELS, DEFAULT_MODEL, get_model_config

# Try to load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not installed, rely on system environment variables

# Try to import Gemini API
try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    genai = None


_configured = False

def configure_gemini() -> bool:
    """
    Configure the Gemini API client with the API key from environment.
    
    Returns:
        True if configuration succeeded, False otherwise.
    """
    global _configured
    if _configured:
        return True
        
    if not GEMINI_AVAILABLE:
        print("[ERROR] google-generativeai package not installed.")
        print("        Run: pip install google-generativeai")
        return False
    
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("[ERROR] GEMINI_API_KEY environment variable not set.")
        print("        Create a .env file with: GEMINI_API_KEY=your-key-here")
        return False
    
    genai.configure(api_key=api_key)
    _configured = True
    return True


def call_llm(prompt: str, model_name: str = DEFAULT_MODEL) -> str:
    """
    Call the Gemini LLM with a prompt.
    
    Args:
        prompt: The prompt text to send.
        model_name: Short model name (flash, flash-lite, pro).
        
    Returns:
        The raw response text from the LLM.
        
    Raises:
        RuntimeError: If the API call fails.
    """
    if not GEMINI_AVAILABLE:
        raise RuntimeError("google-generativeai package not installed")
    
    # Configure API if not already done
    if not configure_gemini():
        raise RuntimeError("Failed to configure Gemini API")
    
    # Get full model ID
    model_id = GEMINI_MODELS.get(model_name, GEMINI_MODELS[DEFAULT_MODEL])
    config = get_model_config(model_name)
    
    # Create model instance
    model = genai.GenerativeModel(model_id)
    
    # Generate response
    generation_config = genai.types.GenerationConfig(
        max_output_tokens=config["max_output_tokens"],
        temperature=config["temperature"],
    )
    
    response = model.generate_content(prompt, generation_config=generation_config)
    
    return response.text


def parse_llm_json(response_text: str) -> dict[str, Any]:
    """
    Parse JSON from LLM response, handling markdown formatting.
    
    Args:
        response_text: Raw response text from LLM.
        
    Returns:
        Parsed JSON as a dict.
        
    Raises:
        json.JSONDecodeError: If parsing fails.
    """
    text = response_text.strip()
    
    # Try to extract JSON from markdown code blocks
    if "```" in text:
        # Look for ```json ... ``` or ``` ... ```
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
        if json_match:
            text = json_match.group(1).strip()
    
    # Remove any trailing text after the JSON
    # Find the last } and truncate there
    last_brace = text.rfind('}')
    if last_brace != -1:
        text = text[:last_brace + 1]
    
    # Try to parse the JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to recover truncated JSON
        return _try_recover_truncated_json(text)


def _try_recover_truncated_json(text: str) -> dict[str, Any]:
    """
    Attempt to recover valid JSON from a truncated response.
    
    This handles cases where the LLM output was cut off mid-JSON.
    
    Args:
        text: Potentially truncated JSON text.
        
    Returns:
        Recovered JSON dict with whatever data could be salvaged.
        
    Raises:
        json.JSONDecodeError: If recovery fails completely.
    """
    # Count braces to understand structure
    open_braces = text.count('{')
    close_braces = text.count('}')
    open_brackets = text.count('[')
    close_brackets = text.count(']')
    
    # Add missing closing characters
    missing_brackets = open_brackets - close_brackets
    missing_braces = open_braces - close_braces
    
    if missing_brackets > 0 or missing_braces > 0:
        # Check if we are inside an open string (odd number of quotes)
        quote_count = text.count('"')
        if quote_count % 2 == 1:
            # We are inside a string, truncate to the last quote
            last_quote = text.rfind('"')
            if last_quote > 0:
                text = text[:last_quote]
        
        # Find where we might be in a partial object/array
        # Look for last complete item
        
        # Try to truncate at last comma or brace/bracket
        # We want to cut off any partial key/value pair
        last_comma = text.rfind(',')
        last_open_brace = text.rfind('{')
        last_open_bracket = text.rfind('[')
        
        cut_point = max(last_comma, last_open_brace, last_open_bracket)
        
        if cut_point > 0:
             # If we cut at comma, remove it. If at brace/bracket, keep it.
            if text[cut_point] == ',':
                text = text[:cut_point]
            else:
                text = text[:cut_point+1]
        
        # Recalculate missing closers using a stack to ensure correct order
        stack = []
        is_escaped = False
        in_string = False
        
        for char in text:
            if in_string:
                if char == '"' and not is_escaped:
                    in_string = False
                elif char == '\\':
                    is_escaped = not is_escaped
                else:
                    is_escaped = False
            else:
                if char == '"':
                    in_string = True
                elif char in '{[':
                    stack.append(char)
                elif char == '}':
                    if stack and stack[-1] == '{':
                        stack.pop()
                elif char == ']':
                    if stack and stack[-1] == '[':
                        stack.pop()
        
        # Close remaining open structures in reverse order
        closers = {'{': '}', '[': ']'}
        closing_str = "".join(closers[c] for c in reversed(stack))
        text += closing_str
    
    print(f"DEBUG: Recovered JSON text: {text}")
    return json.loads(text)

