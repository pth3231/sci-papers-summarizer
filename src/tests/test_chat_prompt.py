from src.routers.chat import SYSTEM_PROMPT


def test_system_prompt_requires_latex_math_contract():
    prompt = SYSTEM_PROMPT.lower()
    # The model must be told to emit LaTeX wrapped in dollar delimiters,
    # not Unicode/ASCII math, so remark-math + KaTeX can render it.
    assert "latex" in prompt
    assert "$...$" in SYSTEM_PROMPT
    assert "$$...$$" in SYSTEM_PROMPT
